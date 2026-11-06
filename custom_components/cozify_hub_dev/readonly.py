"""Read-only mirrors of controllable things.

When a hub is configured as read-only, the light/switch/climate/scene platforms
are not loaded at all. What would have been a switch, a light, a rule switch or
a thermostat setpoint is exposed as a plain (binary) sensor instead, so the
state stays visible to dashboards and automations but nothing in the UI can
write to the hub.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CozifyCoordinator
from .entity import CozifyEntity, CozifyHubEntity

POWER_CAPS = {"ON_OFF"}


def has_power(caps: set[str]) -> bool:
    return bool(caps & POWER_CAPS)


def has_setpoint(caps: set[str]) -> bool:
    return "CONTROL_TEMPERATURE" in caps and "AIRCON" not in caps


class PowerBinarySensor(CozifyEntity, BinarySensorEntity):
    """On/off state of a switch, socket or light (read-only)."""

    _attr_name = "Power"
    _attr_device_class = BinarySensorDeviceClass.POWER

    def __init__(self, coordinator: CozifyCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "power")

    @property
    def is_on(self) -> bool | None:
        value = self.dev_state.get("isOn")
        return None if value is None else bool(value)


class SetpointSensor(CozifyEntity, SensorEntity):
    """Thermostat target temperature (read-only)."""

    _attr_name = "Target temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: CozifyCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "target_temperature")

    @property
    def native_value(self) -> float | None:
        return self.dev_state.get("targetTemp")


class RuleBinarySensor(CozifyHubEntity, BinarySensorEntity):
    """Whether a hub rule is enabled (read-only)."""

    _attr_icon = "mdi:script-text-outline"

    def __init__(self, coordinator: CozifyCoordinator, rule_id: str) -> None:
        super().__init__(coordinator, f"rule_state_{rule_id}")
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
        return {"rule_id": self.rule_id, "rule_type": cfg.get("configType")}


@callback
def add_rule_mirrors(entry, coordinator: CozifyCoordinator, async_add_entities: AddEntitiesCallback) -> None:
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new = [r for r in coordinator.rules if r not in known]
        if new:
            known.update(new)
            async_add_entities([RuleBinarySensor(coordinator, r) for r in new])

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))
