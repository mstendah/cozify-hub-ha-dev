"""Services: scenes, rules, custom rule deployment, proposals, workload advisor."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from . import advisor
from .api import CozifyError
from .const import (
    DOMAIN,
    SERVICE_CREATE_RULE_FROM_PROPOSAL,
    SERVICE_DELETE_RULE,
    SERVICE_DEPLOY_CUSTOM_RULE,
    SERVICE_GET_RULE_LOG,
    SERVICE_GET_RULE_PROPOSALS,
    SERVICE_RUN_SCENE,
    SERVICE_SEND_COMMAND,
    SERVICE_SET_RULE_STATE,
    SERVICE_SUGGEST_WORKLOAD_SPLIT,
)
from .coordinator import CozifyCoordinator
from .rules import RuleError, deploy_custom_rule

_LOGGER = logging.getLogger(__name__)

ENTRY = {vol.Optional("config_entry_id"): cv.string}
ON_OFF = vol.In(["on", "off"])


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> CozifyCoordinator:
    entries = [
        e for e in hass.config_entries.async_entries(DOMAIN) if getattr(e, "runtime_data", None)
    ]
    wanted = call.data.get("config_entry_id")
    if wanted:
        entries = [e for e in entries if e.entry_id == wanted]
    if not entries:
        raise ServiceValidationError("No loaded Cozify Hub entry found")
    if len(entries) > 1:
        raise ServiceValidationError("Several hubs configured: pass config_entry_id")
    return entries[0].runtime_data


def _find(items: dict[str, dict[str, Any]], ref: str, name_of) -> str:
    """Resolve an id or (case-insensitive) name to an id."""
    if ref in items:
        return ref
    matches = [i for i, obj in items.items() if (name_of(obj) or "").lower() == ref.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ServiceValidationError(f"'{ref}' not found on the hub")
    raise ServiceValidationError(f"'{ref}' is ambiguous, use the id")


def cozify_device_id(hub_id: str, unique_id: str | None) -> str | None:
    """Entity unique ids are ``<hub>_<device uuid>_<key>``."""
    prefix = f"{hub_id}_"
    if unique_id and unique_id.startswith(prefix):
        candidate = unique_id[len(prefix) : len(prefix) + 36]
        if len(candidate) == 36 and candidate.count("-") == 4:
            return candidate
    return None


def _wrap(handler):
    async def run(call: ServiceCall) -> ServiceResponse:
        try:
            return await handler(call)
        except RuleError as err:
            raise ServiceValidationError(str(err)) from err
        except CozifyError as err:
            raise HomeAssistantError(f"Cozify hub error: {err}") from err

    return run


def async_register_services(hass: HomeAssistant) -> None:
    async def run_scene(call: ServiceCall) -> ServiceResponse:
        c = _coordinator(hass, call)
        scene_id = _find(c.scenes, call.data["scene"], lambda s: s.get("name"))
        await c.client.scene_command(scene_id, call.data.get("state", "on") == "on")
        return None

    async def set_rule_state(call: ServiceCall) -> ServiceResponse:
        c = _coordinator(hass, call)
        rule_id = _find(c.rules, call.data["rule"], lambda r: (r.get("config") or {}).get("name"))
        await c.client.rule_command(rule_id, call.data["state"] == "on")
        return None

    async def delete_rule(call: ServiceCall) -> ServiceResponse:
        c = _coordinator(hass, call)
        rule_id = _find(c.rules, call.data["rule"], lambda r: (r.get("config") or {}).get("name"))
        if not call.data.get("confirm"):
            raise ServiceValidationError("Set confirm: true to delete a hub rule")
        await c.client.delete_rule(rule_id)
        return None

    async def deploy(call: ServiceCall) -> ServiceResponse:
        c = _coordinator(hass, call)
        source = call.data.get("source")
        if not source:
            path = call.data["file"]
            if not hass.config.is_allowed_path(path):
                raise ServiceValidationError(f"{path} is not in allowlist_external_dirs")
            source = await hass.async_add_executor_job(_read, path)
        result = await deploy_custom_rule(
            c.client,
            source,
            preserve_instances=call.data.get("preserve_instances", True),
            turn_on=call.data.get("turn_on", True),
            new_instance_config=call.data.get("instance"),
        )
        await c.async_request_refresh()
        return result

    async def rule_log(call: ServiceCall) -> ServiceResponse:
        c = _coordinator(hass, call)
        return {"log": await c.client.rule_log(call.data.get("rule_type"))}

    async def proposals(call: ServiceCall) -> ServiceResponse:
        c = _coordinator(hass, call)
        registry = er.async_get(hass)
        device_ids: list[str] = list(call.data.get("device_ids", []))
        for ent_id in call.data.get("entity_ids", []):
            entry = registry.async_get(ent_id)
            dev = cozify_device_id(c.client.hub_id, entry.unique_id if entry else None)
            if dev and dev not in device_ids:
                device_ids.append(dev)
        if not device_ids:
            raise ServiceValidationError("Give entity_ids of Cozify entities or device_ids")
        result = await c.client.rule_proposals(device_ids, call.data.get("room"), call.data.get("max", 5))
        return {"proposals": result}

    async def create_from_proposal(call: ServiceCall) -> ServiceResponse:
        c = _coordinator(hass, call)
        proposal = call.data["proposal"]
        config = dict(proposal.get("config", proposal))
        config["id"] = None
        if call.data.get("name"):
            config["name"] = call.data["name"]
        on_cfg = proposal.get("onConfig") or None
        await c.client.save_rule(config, on_cfg)
        await c.async_request_refresh()
        return None

    async def suggest(call: ServiceCall) -> ServiceResponse:
        c = _coordinator(hass, call)
        recs = await async_run_advisor(hass, c)
        markdown = advisor.render_markdown(recs)
        if call.data.get("notify"):
            from homeassistant.components import persistent_notification

            persistent_notification.async_create(
                hass, markdown, title="Cozify Hub workload suggestions", notification_id=f"{DOMAIN}_advisor"
            )
        return {
            "summary": advisor.summarize(recs),
            "automations": [r.as_dict() for r in recs if r.verdict != "not_related"],
            "markdown": markdown,
        }

    async def send_command(call: ServiceCall) -> ServiceResponse:
        c = _coordinator(hass, call)
        await c.client.device_command(call.data["commands"])
        return None

    def reg(name: str, handler, schema: dict, response: SupportsResponse = SupportsResponse.NONE) -> None:
        hass.services.async_register(
            DOMAIN, name, _wrap(handler), schema=vol.Schema({**ENTRY, **schema}), supports_response=response
        )

    reg(SERVICE_RUN_SCENE, run_scene, {vol.Required("scene"): cv.string, vol.Optional("state", default="on"): ON_OFF})
    reg(SERVICE_SET_RULE_STATE, set_rule_state, {vol.Required("rule"): cv.string, vol.Required("state"): ON_OFF})
    reg(SERVICE_DELETE_RULE, delete_rule, {vol.Required("rule"): cv.string, vol.Required("confirm"): cv.boolean})
    reg(
        SERVICE_DEPLOY_CUSTOM_RULE,
        deploy,
        {
            vol.Exclusive("source", "src"): cv.string,
            vol.Exclusive("file", "src"): cv.string,
            vol.Optional("preserve_instances", default=True): cv.boolean,
            vol.Optional("turn_on", default=True): cv.boolean,
            vol.Optional("instance"): dict,
        },
        SupportsResponse.OPTIONAL,
    )
    reg(SERVICE_GET_RULE_LOG, rule_log, {vol.Optional("rule_type"): cv.string}, SupportsResponse.ONLY)
    reg(
        SERVICE_GET_RULE_PROPOSALS,
        proposals,
        {
            vol.Optional("entity_ids", default=[]): cv.entity_ids,
            vol.Optional("device_ids", default=[]): [cv.string],
            vol.Optional("room"): cv.string,
            vol.Optional("max", default=5): vol.All(int, vol.Range(min=1, max=20)),
        },
        SupportsResponse.ONLY,
    )
    reg(
        SERVICE_CREATE_RULE_FROM_PROPOSAL,
        create_from_proposal,
        {vol.Required("proposal"): dict, vol.Optional("name"): cv.string},
    )
    reg(SERVICE_SUGGEST_WORKLOAD_SPLIT, suggest, {vol.Optional("notify", default=False): cv.boolean},
        SupportsResponse.ONLY)
    reg(SERVICE_SEND_COMMAND, send_command, {vol.Required("commands"): [dict]})


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:  # noqa: PTH123
        return fh.read()


def _automation_configs(hass: HomeAssistant) -> list[tuple[str, dict[str, Any]]]:
    """Return (entity_id, raw_config) for loaded automations."""
    try:
        from homeassistant.components.automation import DATA_COMPONENT
    except ImportError:  # pragma: no cover - HA internals moved
        return []
    component = hass.data.get(DATA_COMPONENT)
    if component is None:
        return []
    out = []
    for entity in component.entities:
        raw = getattr(entity, "raw_config", None)
        if isinstance(raw, dict):
            out.append((entity.entity_id, raw))
    return out


async def async_run_advisor(hass: HomeAssistant, c: CozifyCoordinator) -> list[advisor.Recommendation]:
    registry = er.async_get(hass)
    entry_id = c.config_entry.entry_id
    hub_entities, classes = set(), {}
    for ent in er.async_entries_for_config_entry(registry, entry_id):
        hub_entities.add(ent.entity_id)
        cls = ent.device_class or ent.original_device_class
        if cls:
            classes[ent.entity_id] = str(cls)
    hub_devices = {
        d.id for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry_id)
    }
    templates: list[dict[str, Any]] = []
    try:
        raw = await c.client.rule_templates()
        templates = raw if isinstance(raw, list) else [{"type": k, **(v if isinstance(v, dict) else {})} for k, v in (raw or {}).items()]
    except CozifyError as err:
        _LOGGER.debug("Could not fetch rule templates: %s", err)
    connection = "local" if c.client.is_local else "cloud"
    return [
        advisor.analyze_automation(
            ent_id, cfg, hub_entities=hub_entities, hub_device_ids=hub_devices,
            entity_classes=classes, rule_templates=templates, connection=connection,
        )
        for ent_id, cfg in _automation_configs(hass)
    ]
