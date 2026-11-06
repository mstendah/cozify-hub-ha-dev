"""Binary sensors from curated definitions plus spec-driven fallbacks."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import spec
from .coordinator import CozifyCoordinator
from .entity import CozifyEntity, setup_device_platform
from .entity_defs import CONTROL_CAPABILITIES, CURATED_ATTRS, CURATED_BINARY, BinaryDef
from .sensor import _humanize


class CozifyBinarySensor(CozifyEntity, BinarySensorEntity):
    def __init__(self, coordinator: CozifyCoordinator, device_id: str, d: BinaryDef) -> None:
        super().__init__(coordinator, device_id, d.key)
        self._def = d
        self._attr_name = d.name
        self._attr_device_class = d.device_class
        self._attr_entity_category = d.category
        self._attr_entity_registry_enabled_default = d.enabled

    @property
    def available(self) -> bool:
        # Connectivity must stay available when the device is unreachable.
        if self._def.key == "reachable":
            return self.coordinator.last_update_success and self.device_id in self.coordinator.devices
        return super().available

    @property
    def is_on(self) -> bool | None:
        value = self._def.value(self.dev_state)
        return None if value is None else bool(value)


def _defs_for(coordinator: CozifyCoordinator, device_id: str) -> list[BinaryDef]:
    caps = coordinator.capabilities(device_id)
    state = coordinator.devices[device_id].get("state") or {}
    defs: list[BinaryDef] = []
    used: set[str] = set()
    for cap in sorted(caps):
        for d in CURATED_BINARY.get(cap, []):
            if d.key in {"smoke"} and "GENERATE_ALERT" in caps and "SMOKE" not in caps:
                continue
            defs.append(d)
        used |= CURATED_ATTRS.get(cap, set())
    for cap in sorted(caps):
        if cap in CONTROL_CAPABILITIES or not spec.is_known_capability(cap):
            continue
        for attr in spec.capability_attributes(cap):
            key = spec.state_key(attr["path"])
            if key is None or attr.get("writable") or key in used or attr.get("type") != "boolean":
                continue
            if key not in state or key in {"alert", "isOn"}:
                continue
            used.add(key)
            defs.append(
                BinaryDef(f"x_{key}", _humanize(key), (lambda k: lambda s: s.get(k))(key),
                          None, EntityCategory.DIAGNOSTIC, False)
            )
    return defs


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_device_platform(
        hass, entry, async_add_entities,
        lambda c, dev_id: [CozifyBinarySensor(c, dev_id, d) for d in _defs_for(c, dev_id)],
    )
