"""Shared entity helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, SIGNAL_NEW_DEVICES
from .coordinator import CozifyCoordinator


def hub_device_info(coordinator: CozifyCoordinator) -> DeviceInfo:
    client = coordinator.client
    return DeviceInfo(
        identifiers={(DOMAIN, client.hub_id)},
        name=client.name or "Cozify Hub",
        manufacturer=MANUFACTURER,
        model="Cozify Hub",
        sw_version=client.version,
    )


class CozifyEntity(CoordinatorEntity[CozifyCoordinator]):
    """Entity bound to one Cozify device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CozifyCoordinator, device_id: str, key: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self._key = key
        self._attr_unique_id = f"{coordinator.client.hub_id}_{device_id}_{key}"

    @property
    def device(self) -> dict[str, Any]:
        return self.coordinator.devices.get(self.device_id, {})

    @property
    def dev_state(self) -> dict[str, Any]:
        return self.device.get("state") or {}

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.device_id in self.coordinator.devices
            and bool(self.dev_state.get("reachable", True))
        )

    @property
    def device_info(self) -> DeviceInfo:
        dev = self.device
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.coordinator.client.hub_id}_{self.device_id}")},
            name=dev.get("name") or self.device_id,
            manufacturer=dev.get("manufacturer") or MANUFACTURER,
            model=dev.get("model"),
            suggested_area=self.coordinator.room_name(dev),
            via_device=(DOMAIN, self.coordinator.client.hub_id),
        )


class CozifyHubEntity(CoordinatorEntity[CozifyCoordinator]):
    """Entity that belongs to the hub itself (rules, scenes, diagnostics)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CozifyCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.client.hub_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return hub_device_info(self.coordinator)


def setup_device_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    build: Callable[[CozifyCoordinator, str], list[Any]],
) -> None:
    """Add entities for existing devices and for devices that appear later."""
    coordinator: CozifyCoordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def _add(device_ids: set[str] | None = None) -> None:
        ids = device_ids if device_ids is not None else set(coordinator.devices)
        entities: list[Any] = []
        for dev_id in ids:
            if dev_id in added or dev_id not in coordinator.devices:
                continue
            added.add(dev_id)
            entities.extend(build(coordinator, dev_id))
        if entities:
            async_add_entities(entities)

    _add()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_DEVICES.format(coordinator.client.hub_id), _add)
    )
