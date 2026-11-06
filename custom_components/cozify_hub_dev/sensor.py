"""Sensors: curated per capability plus spec-driven generic fallbacks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import spec
from .coordinator import CozifyCoordinator
from .entity import CozifyEntity, CozifyHubEntity, setup_device_platform
from .entity_defs import CONTROL_CAPABILITIES, CURATED_ATTRS, CURATED_SENSORS, SensorDef


def _humanize(key: str) -> str:
    out = ""
    for ch in key:
        out += (" " + ch.lower()) if ch.isupper() else ch
    return out.replace("_", " ").strip().capitalize()


class CozifySensor(CozifyEntity, SensorEntity):
    def __init__(self, coordinator: CozifyCoordinator, device_id: str, d: SensorDef) -> None:
        super().__init__(coordinator, device_id, d.key)
        self._def = d
        self._attr_name = d.name
        self._attr_device_class = d.device_class
        self._attr_native_unit_of_measurement = d.unit
        self._attr_state_class = d.state_class
        self._attr_entity_category = d.category
        self._attr_entity_registry_enabled_default = d.enabled

    @property
    def native_value(self) -> Any:
        value = self._def.value(self.dev_state)
        if value is None:
            return None
        if self._def.device_class is SensorDeviceClass.TIMESTAMP:
            try:
                return datetime.fromtimestamp(float(value) / 1000, UTC)
            except (TypeError, ValueError, OverflowError):
                return None
        # Hub reports -1 for "unused" on some measurement fields.
        if self._def.device_class is SensorDeviceClass.TEMPERATURE and value == -1:
            return None
        return value


def _sensor_defs_for(coordinator: CozifyCoordinator, device_id: str) -> list[SensorDef]:
    caps = coordinator.capabilities(device_id)
    state = coordinator.devices[device_id].get("state") or {}
    defs: list[SensorDef] = []
    used: set[str] = set()
    for cap in sorted(caps):
        for d in CURATED_SENSORS.get(cap, []):
            defs.append(d)
        used |= CURATED_ATTRS.get(cap, set())
    # last seen is useful but noisy -> disabled diagnostic
    defs.append(
        SensorDef("last_seen", "Last seen", lambda s: s.get("lastSeen"),
                  SensorDeviceClass.TIMESTAMP, None, None, EntityCategory.DIAGNOSTIC, False)
    )
    # Spec-driven generic fallbacks for everything documented but not curated.
    for cap in sorted(caps):
        if cap in CONTROL_CAPABILITIES or not spec.is_known_capability(cap):
            continue
        for attr in spec.capability_attributes(cap):
            key = spec.state_key(attr["path"])
            if (
                key is None
                or attr.get("writable")
                or key in used
                or key not in state
                or key in {"lastSeen", "reachable", "alert", "isOn"}
            ):
                continue
            kind = attr.get("type")
            if kind not in {"int", "float", "timestampms", "enum", None}:
                continue
            value = state.get(key)
            if isinstance(value, (list, dict)):
                continue
            used.add(key)
            defs.append(
                SensorDef(
                    f"x_{key}", _humanize(key), (lambda k: lambda s: s.get(k))(key),
                    SensorDeviceClass.TIMESTAMP if kind == "timestampms" else None,
                    attr.get("unit") if kind != "timestampms" else None, None,
                    EntityCategory.DIAGNOSTIC, False,
                )
            )
    return defs


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: CozifyCoordinator = entry.runtime_data
    from . import is_read_only
    from .readonly import SetpointSensor, has_setpoint

    read_only = is_read_only(entry)

    def build(c: CozifyCoordinator, dev_id: str) -> list:
        ents: list = [CozifySensor(c, dev_id, d) for d in _sensor_defs_for(c, dev_id)]
        if read_only and has_setpoint(c.capabilities(dev_id)):
            ents.append(SetpointSensor(c, dev_id))
        return ents

    setup_device_platform(hass, entry, async_add_entities, build)
    async_add_entities(
        [HubConnectionSensor(coordinator), HubVersionSensor(coordinator), HubSpecSensor(coordinator),
         HubModeSensor(coordinator, read_only)]
    )


class HubConnectionSensor(CozifyHubEntity, SensorEntity):
    _attr_name = "Connection"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["local", "cloud"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: CozifyCoordinator) -> None:
        super().__init__(coordinator, "connection")

    @property
    def native_value(self) -> str:
        return "local" if self.coordinator.client.is_local else "cloud"


class HubModeSensor(CozifyHubEntity, SensorEntity):
    """Whether this hub is read-only. Lets dashboards adapt to the access mode."""

    _attr_name = "Access mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["read_only", "full"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: CozifyCoordinator, read_only: bool) -> None:
        super().__init__(coordinator, "access_mode")
        self._read_only = read_only

    @property
    def native_value(self) -> str:
        return "read_only" if self._read_only else "full"


class HubVersionSensor(CozifyHubEntity, SensorEntity):
    _attr_name = "Software version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: CozifyCoordinator) -> None:
        super().__init__(coordinator, "version")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.client.version


class HubSpecSensor(CozifyHubEntity, SensorEntity):
    """Which revision of the API documentation this integration was built from."""

    _attr_name = "API documentation revision"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: CozifyCoordinator) -> None:
        super().__init__(coordinator, "spec_revision")

    @property
    def native_value(self) -> str | None:
        return spec.docs_revision()
