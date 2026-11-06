"""Light platform (CONTROL_LIGHT devices)."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CozifyCoordinator
from .entity import CozifyEntity, setup_device_platform

# Colour mode names used in STATE_LIGHT.colorMode. "hs" is documented; "ct" is
# the hub's name for colour temperature (not spelled out in the docs yet).
MODE_HS = "hs"
MODE_CT = "ct"


class CozifyLight(CozifyEntity, LightEntity):
    _attr_name = None

    def __init__(self, coordinator: CozifyCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "light")
        caps = coordinator.capabilities(device_id)
        modes: set[ColorMode] = set()
        if "COLOR_HS" in caps:
            modes.add(ColorMode.HS)
        if "COLOR_TEMP" in caps:
            modes.add(ColorMode.COLOR_TEMP)
        if not modes:
            modes.add(ColorMode.BRIGHTNESS if "BRIGHTNESS" in caps else ColorMode.ONOFF)
        self._attr_supported_color_modes = modes
        if "TRANSITION" in caps:
            self._attr_supported_features = LightEntityFeature.TRANSITION

    @property
    def is_on(self) -> bool | None:
        return self.dev_state.get("isOn")

    @property
    def brightness(self) -> int | None:
        value = self.dev_state.get("brightness")
        return None if value is None else max(1, round(float(value) * 255))

    @property
    def color_mode(self) -> ColorMode:
        modes = self._attr_supported_color_modes
        mode = self.dev_state.get("colorMode")
        if mode == MODE_HS and ColorMode.HS in modes:
            return ColorMode.HS
        if mode == MODE_CT and ColorMode.COLOR_TEMP in modes:
            return ColorMode.COLOR_TEMP
        for candidate in (ColorMode.HS, ColorMode.COLOR_TEMP, ColorMode.BRIGHTNESS, ColorMode.ONOFF):
            if candidate in modes:
                return candidate
        return ColorMode.ONOFF

    @property
    def hs_color(self) -> tuple[float, float] | None:
        hue, sat = self.dev_state.get("hue"), self.dev_state.get("saturation")
        if hue is None or sat is None:
            return None
        return (round(math.degrees(hue) % 360, 1), round(sat * 100, 1))

    @property
    def color_temp_kelvin(self) -> int | None:
        value = self.dev_state.get("temperature")
        return int(value) if isinstance(value, (int, float)) and value > 0 else None

    @property
    def min_color_temp_kelvin(self) -> int:
        return int(self.dev_state.get("minTemperature") or 2000)

    @property
    def max_color_temp_kelvin(self) -> int:
        return int(self.dev_state.get("maxTemperature") or 6500)

    async def async_turn_on(self, **kwargs: Any) -> None:
        state: dict[str, Any] = {"type": "STATE_LIGHT", "isOn": True}
        patch: dict[str, Any] = {"isOn": True}
        if ATTR_BRIGHTNESS in kwargs:
            state["brightness"] = patch["brightness"] = round(kwargs[ATTR_BRIGHTNESS] / 255, 3)
        if ATTR_HS_COLOR in kwargs:
            hue, sat = kwargs[ATTR_HS_COLOR]
            state.update(colorMode=MODE_HS, hue=math.radians(hue), saturation=sat / 100)
            patch.update(colorMode=MODE_HS, hue=state["hue"], saturation=state["saturation"])
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            state.update(colorMode=MODE_CT, temperature=int(kwargs[ATTR_COLOR_TEMP_KELVIN]))
            patch.update(colorMode=MODE_CT, temperature=state["temperature"])
        if ATTR_TRANSITION in kwargs:
            state["transitionMsec"] = int(float(kwargs[ATTR_TRANSITION]) * 1000)
        if len(state) == 2:  # only on
            await self.coordinator.async_send(
                [{"type": "CMD_DEVICE_ON", "id": self.device_id}], {self.device_id: patch}
            )
        else:
            await self.coordinator.async_send(
                [{"type": "CMD_DEVICE", "id": self.device_id, "state": state}], {self.device_id: patch}
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        if ATTR_TRANSITION in kwargs:
            cmd = {
                "type": "CMD_DEVICE",
                "id": self.device_id,
                "state": {
                    "type": "STATE_LIGHT",
                    "isOn": False,
                    "transitionMsec": int(float(kwargs[ATTR_TRANSITION]) * 1000),
                },
            }
        else:
            cmd = {"type": "CMD_DEVICE_OFF", "id": self.device_id}
        await self.coordinator.async_send([cmd], {self.device_id: {"isOn": False}})


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_device_platform(
        hass, entry, async_add_entities,
        lambda c, dev_id: [CozifyLight(c, dev_id)] if "CONTROL_LIGHT" in c.capabilities(dev_id) else [],
    )
