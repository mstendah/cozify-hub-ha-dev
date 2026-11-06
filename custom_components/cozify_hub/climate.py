"""Thermostats (CONTROL_TEMPERATURE without AIRCON)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CozifyCoordinator
from .entity import CozifyEntity, setup_device_platform


class CozifyThermostat(CozifyEntity, ClimateEntity):
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp = 5.0
    _attr_max_temp = 35.0
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: CozifyCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "climate")

    @property
    def current_temperature(self) -> float | None:
        return self.dev_state.get("temperature")

    @property
    def target_temperature(self) -> float | None:
        return self.dev_state.get("targetTemp")

    @property
    def hvac_action(self) -> HVACAction | None:
        demand = self.dev_state.get("heatingDemand")
        if demand is None:
            return None
        return HVACAction.HEATING if demand > 0 else HVACAction.IDLE

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (target := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self.coordinator.async_send(
            [{"type": "CMD_DEVICE", "id": self.device_id,
              "state": {"type": "STATE_THERMOSTAT", "targetTemp": float(target)}}],
            {self.device_id: {"targetTemp": float(target)}},
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def build(c: CozifyCoordinator, dev_id: str) -> list[Any]:
        caps = c.capabilities(dev_id)
        if "CONTROL_TEMPERATURE" in caps and "AIRCON" not in caps:
            return [CozifyThermostat(c, dev_id)]
        return []

    setup_device_platform(hass, entry, async_add_entities, build)
