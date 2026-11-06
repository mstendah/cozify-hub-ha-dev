"""Switches: switchable devices and hub rules."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_READ_ONLY, DOMAIN
from .coordinator import CozifyCoordinator
from .entity import CozifyEntity, CozifyHubEntity, setup_device_platform


def is_switch_device(caps: set[str]) -> bool:
    return (
        "ON_OFF" in caps
        and not caps & {"CONTROL_LIGHT", "AIRCON", "SHUTTER", "LIFT", "PLAY", "PAUSE", "RECORD_VIDEO"}
    )


class CozifySwitch(CozifyEntity, SwitchEntity):
    _attr_name = None

    def __init__(self, coordinator: CozifyCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "switch")
        if "CONTROL_POWER" in coordinator.capabilities(device_id):
            self._attr_device_class = SwitchDeviceClass.OUTLET

    @property
    def is_on(self) -> bool | None:
        return self.dev_state.get("isOn")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send(
            [{"type": "CMD_DEVICE_ON", "id": self.device_id}], {self.device_id: {"isOn": True}}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send(
            [{"type": "CMD_DEVICE_OFF", "id": self.device_id}], {self.device_id: {"isOn": False}}
        )


class CozifyRuleSwitch(CozifyHubEntity, SwitchEntity):
    """A hub rule as a switch - enables/disables it from HA automations."""

    _attr_icon = "mdi:script-text-outline"

    def __init__(self, coordinator: CozifyCoordinator, rule_id: str) -> None:
        super().__init__(coordinator, f"rule_{rule_id}")
        self.rule_id = rule_id

    @property
    def rule(self) -> dict[str, Any]:
        return self.coordinator.rules.get(self.rule_id, {})

    @property
    def name(self) -> str:  # type: ignore[override]
        cfg = self.rule.get("config") or {}
        return f"Rule: {cfg.get('name') or self.rule_id}"

    @property
    def available(self) -> bool:
        return super().available and self.rule_id in self.coordinator.rules

    @property
    def is_on(self) -> bool | None:
        value = self.rule.get("is_on")
        return None if value is None else bool(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cfg = self.rule.get("config") or {}
        return {
            "rule_id": self.rule_id,
            "rule_type": cfg.get("configType"),
            "inputs": cfg.get("inputs"),
            "outputs": cfg.get("outputs"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.rule_command(self.rule_id, True)
        self.rule["is_on"] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.rule_command(self.rule_id, False)
        self.rule["is_on"] = False
        self.async_write_ha_state()


class ReadOnlySwitch(CozifyHubEntity, SwitchEntity):
    """Toggle for the integration's read-only mode.

    This only changes the integration's own setting (the config entry options); it never
    talks to the hub. Switching reloads the entry, so controllable entities appear or
    disappear accordingly.
    """

    _attr_name = "Read-only mode"
    _attr_icon = "mdi:lock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: CozifyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, "read_only")
        self._entry = entry

    @property
    def available(self) -> bool:
        return True  # a setting of the integration, usable even while the hub is unreachable

    @property
    def is_on(self) -> bool:
        from . import is_read_only

        return is_read_only(self._entry)

    async def _set(self, value: bool) -> None:
        if self.is_on == value:
            return
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, CONF_READ_ONLY: value}
        )  # the update listener reloads the entry

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    from . import is_read_only

    coordinator: CozifyCoordinator = entry.runtime_data
    async_add_entities([ReadOnlySwitch(coordinator, entry)])
    if is_read_only(entry):
        return  # nothing else that could write to the hub
    setup_device_platform(
        hass, entry, async_add_entities,
        lambda c, dev_id: [CozifySwitch(c, dev_id)] if is_switch_device(c.capabilities(dev_id)) else [],
    )

    known: set[str] = set()

    @callback
    def _sync_rules() -> None:
        new = [r for r in coordinator.rules if r not in known]
        if new:
            known.update(new)
            async_add_entities([CozifyRuleSwitch(coordinator, r) for r in new])
        # Rules removed on the hub: drop their registry entries.
        gone = known - set(coordinator.rules)
        if gone and coordinator.last_update_success:
            registry = er.async_get(hass)
            for rule_id in gone:
                unique = f"{coordinator.client.hub_id}_rule_{rule_id}"
                ent = registry.async_get_entity_id("switch", DOMAIN, unique)
                if ent:
                    registry.async_remove(ent)
                known.discard(rule_id)

    _sync_rules()
    entry.async_on_unload(coordinator.async_add_listener(_sync_rules))
