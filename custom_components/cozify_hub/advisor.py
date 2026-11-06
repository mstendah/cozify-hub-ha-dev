"""Workload advisor: which automations belong on the hub and which in HA.

The hub runs rules locally: they keep working when Home Assistant restarts, the
network is down or the cloud is unreachable, and they react without a round
trip. Home Assistant is better when logic needs other integrations, templates,
notifications, presence or AI. The advisor reads your automations, looks at the
entities they use and recommends where each should run.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

# Services that only act on hub-style devices
LOCAL_SERVICE_DOMAINS = {"light", "switch", "scene", "climate", "homeassistant", "cozify_hub", "input_boolean_off"}
# Services that need HA only (or other integrations)
HA_ONLY_SERVICE_DOMAINS = {
    "notify", "tts", "persistent_notification", "media_player", "camera", "conversation",
    "mqtt", "rest_command", "shell_command", "script", "python_script", "telegram_bot",
    "assist_satellite", "ai_task", "weather",
}
COMPLEX_KEYS = {"choose", "repeat", "wait_template", "wait_for_trigger", "parallel", "sequence", "variables", "if"}
EXTERNAL_TRIGGERS = {"webhook", "mqtt", "zone", "geo_location", "calendar", "conversation", "sun", "tag", "persistent_notification", "device_tracker"}
SAFETY_CLASSES = ("smoke", "moisture", "flood", "leak", "co2", "gas", "water")
_TEMPLATE_ENTITY = re.compile(
    r"""(?:states|is_state|state_attr|is_state_attr|has_value)\(\s*['"]([a-z_]+\.[a-z0-9_]+)['"]"""
)
_STATES_DOT = re.compile(r"states\.([a-z_]+)\.([a-z0-9_]+)")
_ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


@dataclass
class Recommendation:
    automation: str
    alias: str
    verdict: str  # move_to_hub | split | keep_in_ha | not_related
    score: int  # 0-100 suitability for running on the hub
    reasons: list[str] = field(default_factory=list)
    hub_entities: list[str] = field(default_factory=list)
    other_entities: list[str] = field(default_factory=list)
    suggested_hub_template: str | None = None
    next_step: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _walk(node: Any, visit) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            visit(k, v)
            _walk(v, visit)
    elif isinstance(node, list):
        for item in node:
            _walk(item, visit)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def extract_references(config: dict[str, Any]) -> dict[str, Any]:
    """Collect entities, device ids, services, templates and complexity markers."""
    entities: set[str] = set()
    devices: set[str] = set()
    services: set[str] = set()
    complex_found: set[str] = set()
    templates = 0
    triggers_platforms: set[str] = set()

    def visit(key: str, value: Any) -> None:
        nonlocal templates
        if key in ("entity_id", "entity"):
            for v in _as_list(value):
                if isinstance(v, str):
                    if _ENTITY_RE.match(v):
                        entities.add(v)
                    for m in _TEMPLATE_ENTITY.finditer(v):
                        entities.add(m.group(1))
        elif key == "device_id":
            for v in _as_list(value):
                if isinstance(v, str):
                    devices.add(v)
        elif key in ("action", "service") and isinstance(value, str) and "." in value and "{{" not in value:
            services.add(value)
        elif key in COMPLEX_KEYS:
            complex_found.add(key)
        if isinstance(value, str) and ("{{" in value or "{%" in value):
            templates += 1
            for m in _TEMPLATE_ENTITY.finditer(value):
                entities.add(m.group(1))
            for m in _STATES_DOT.finditer(value):
                entities.add(f"{m.group(1)}.{m.group(2)}")

    _walk(config, visit)
    for trig in _as_list(config.get("triggers", config.get("trigger"))):
        if isinstance(trig, dict):
            plat = trig.get("trigger") or trig.get("platform")
            if plat:
                triggers_platforms.add(str(plat))
    return {
        "entities": entities,
        "devices": devices,
        "services": services,
        "complex": complex_found,
        "templates": templates,
        "trigger_platforms": triggers_platforms,
    }


def _trigger_entities(config: dict[str, Any]) -> tuple[set[str], set[str]]:
    ents: set[str] = set()
    devs: set[str] = set()
    for trig in _as_list(config.get("triggers", config.get("trigger"))):
        if isinstance(trig, dict):
            refs = extract_references(trig)
            ents |= refs["entities"]
            devs |= refs["devices"]
    return ents, devs


def analyze_automation(
    automation_id: str,
    config: dict[str, Any],
    *,
    hub_entities: set[str],
    hub_device_ids: set[str] | None = None,
    entity_classes: dict[str, str] | None = None,
    rule_templates: list[dict[str, Any]] | None = None,
    connection: str = "local",
) -> Recommendation:
    """Classify one automation. Pure function so it is easy to test."""
    hub_device_ids = hub_device_ids or set()
    entity_classes = entity_classes or {}
    alias = str(config.get("alias") or automation_id)
    refs = extract_references(config)
    all_entities: set[str] = refs["entities"]
    hub_ents = {e for e in all_entities if e in hub_entities}
    other_ents = all_entities - hub_ents
    hub_devs = refs["devices"] & hub_device_ids
    other_devs = refs["devices"] - hub_device_ids
    rec = Recommendation(
        automation=automation_id,
        alias=alias,
        verdict="not_related",
        score=0,
        hub_entities=sorted(hub_ents),
        other_entities=sorted(other_ents | other_devs),
    )
    if not hub_ents and not hub_devs:
        rec.reasons.append("Does not use any Cozify Hub entities.")
        return rec

    t_ents, t_devs = _trigger_entities(config)
    triggers_hub_only = bool(t_ents | t_devs) and all(e in hub_entities for e in t_ents) and t_devs <= hub_device_ids
    services = refs["services"]
    service_domains = {s.split(".", 1)[0] for s in services}
    ha_only = sorted(service_domains & HA_ONLY_SERVICE_DOMAINS)
    foreign_services = sorted(service_domains - LOCAL_SERVICE_DOMAINS - HA_ONLY_SERVICE_DOMAINS)
    external_triggers = sorted(refs["trigger_platforms"] & EXTERNAL_TRIGGERS)
    complex_keys = sorted(refs["complex"])
    templates = refs["templates"]

    score = 50
    if triggers_hub_only:
        score += 20
        rec.reasons.append("All triggers come from Cozify Hub devices.")
    if not other_ents and not other_devs:
        score += 20
        rec.reasons.append("Only Cozify Hub entities are used.")
    else:
        score -= 15
        rec.reasons.append(f"Also depends on {len(other_ents | other_devs)} non-Cozify entities/devices.")
    if ha_only:
        score -= 30
        rec.reasons.append("Uses Home Assistant only services: " + ", ".join(ha_only) + ".")
    if foreign_services:
        score -= 15
        rec.reasons.append("Calls services of other integrations: " + ", ".join(foreign_services) + ".")
    if external_triggers:
        score -= 25
        rec.reasons.append("Triggers on Home Assistant context (" + ", ".join(external_triggers) + ").")
    if complex_keys:
        score -= 10 * min(len(complex_keys), 3)
        rec.reasons.append("Uses advanced flow control: " + ", ".join(complex_keys) + ".")
    if templates:
        score -= 10
        rec.reasons.append("Contains Jinja templates (hub rules cannot evaluate them).")
    safety = [e for e in hub_ents if entity_classes.get(e) in SAFETY_CLASSES]
    if safety:
        score += 15
        rec.reasons.append("Safety related (" + ", ".join(sorted({entity_classes[e] for e in safety})) +
                           "): should keep working when Home Assistant is down.")
    if connection == "cloud":
        score += 5
        rec.reasons.append("This hub is reached through the cloud, so a local rule avoids that latency.")
    rec.score = max(0, min(100, score))

    # Verdict
    if rec.score >= 75 and not ha_only and not external_triggers:
        rec.verdict = "move_to_hub"
        rec.next_step = (
            "Recreate it as a hub rule (native template or a custom rule via cozify_hub.deploy_custom_rule), "
            "then disable the HA automation."
        )
    elif triggers_hub_only and (ha_only or other_ents or foreign_services) and hub_ents:
        rec.verdict = "split"
        rec.next_step = (
            "Let a hub rule do the device reaction and keep only the notification/integration part in HA, "
            "triggered by the rule's switch or the cozify_hub_event event."
        )
    elif rec.score >= 55 and not ha_only:
        rec.verdict = "split"
        rec.next_step = "Move the Cozify-only actions to a hub scene (cozify_hub.run_scene) and keep the logic in HA."
    else:
        rec.verdict = "keep_in_ha"
        rec.next_step = "Keep in Home Assistant."

    # Native template hint
    if rec.verdict in ("move_to_hub", "split") and rule_templates:
        classes = {entity_classes.get(e) for e in hub_ents}
        wants_light = any(e.startswith("light.") for e in hub_ents)
        if "motion" in classes and wants_light:
            for t in rule_templates:
                name = str(t.get("type") or t.get("name") or "")
                if "AUTO_LIGHT" in name.upper():
                    rec.suggested_hub_template = name
                    break
    return rec


def summarize(recs: list[Recommendation]) -> dict[str, Any]:
    out = {"total": len(recs)}
    for verdict in ("move_to_hub", "split", "keep_in_ha", "not_related"):
        out[verdict] = sum(1 for r in recs if r.verdict == verdict)
    return out


def render_markdown(recs: list[Recommendation]) -> str:
    lines = ["# Cozify Hub workload suggestions", ""]
    labels = {"move_to_hub": "Move to the hub", "split": "Split between hub and Home Assistant",
              "keep_in_ha": "Keep in Home Assistant"}
    for verdict, label in labels.items():
        group = [r for r in recs if r.verdict == verdict]
        if not group:
            continue
        lines.append(f"## {label}")
        for r in sorted(group, key=lambda r: -r.score):
            lines.append(f"- **{r.alias}** (hub fit {r.score}/100)")
            for reason in r.reasons[:4]:
                lines.append(f"  - {reason}")
            if r.suggested_hub_template:
                lines.append(f"  - Native hub template: `{r.suggested_hub_template}`")
            if r.next_step:
                lines.append(f"  - Next: {r.next_step}")
        lines.append("")
    return "\n".join(lines)
