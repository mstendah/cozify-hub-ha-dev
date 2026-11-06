"""Curated presentation for spec-defined attributes.

Everything the documentation defines but this table does not know still gets an
entity: a generic, diagnostic, disabled-by-default sensor/binary_sensor. That is
how the integration keeps up when the API documentation grows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import homeassistant.const as _const
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
)

# Newer Home Assistant moved ppm to UnitOfRatio; keep working on older cores too.
CONCENTRATION_PARTS_PER_MILLION = (
    _const.UnitOfRatio.PARTS_PER_MILLION
    if hasattr(_const, "UnitOfRatio")
    else _const.CONCENTRATION_PARTS_PER_MILLION
)

# Capabilities that are covered by dedicated platforms; their writable
# attributes are controls, not sensors.
CONTROL_CAPABILITIES = {
    "ON_OFF", "CONTROL_LIGHT", "BRIGHTNESS", "COLOR_HS", "COLOR_TEMP", "TRANSITION",
    "COLOR_RGB", "COLOR_XY", "COLOR_LOOP", "CONTROL_TEMPERATURE", "LIFT", "TILT", "SHUTTER",
}


@dataclass(frozen=True)
class SensorDef:
    key: str
    name: str
    value: Callable[[dict[str, Any]], Any]
    device_class: SensorDeviceClass | None = None
    unit: str | None = None
    state_class: SensorStateClass | None = None
    category: EntityCategory | None = None
    enabled: bool = True
    precision: int | None = None


@dataclass(frozen=True)
class BinaryDef:
    key: str
    name: str
    value: Callable[[dict[str, Any]], Any]
    device_class: BinarySensorDeviceClass | None = None
    category: EntityCategory | None = None
    enabled: bool = True


def _get(k: str) -> Callable[[dict[str, Any]], Any]:
    return lambda s: s.get(k)


def _phase(k: str, i: int) -> Callable[[dict[str, Any]], Any]:
    def getter(s: dict[str, Any]) -> Any:
        v = s.get(k)
        return v[i] if isinstance(v, list) and len(v) > i else None

    return getter


M = SensorStateClass.MEASUREMENT
CURATED_SENSORS: dict[str, list[SensorDef]] = {
    "TEMPERATURE": [SensorDef("temperature", "Temperature", _get("temperature"),
        SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, M)],
    "HUMIDITY": [SensorDef("humidity", "Humidity", _get("humidity"),
        SensorDeviceClass.HUMIDITY, PERCENTAGE, M)],
    "CO2": [SensorDef("co2", "Carbon dioxide", _get("co2Ppm"),
        SensorDeviceClass.CO2, CONCENTRATION_PARTS_PER_MILLION, M)],
    "PRESSURE": [SensorDef("pressure", "Pressure", _get("pressure"),
        SensorDeviceClass.PRESSURE, UnitOfPressure.PA, M)],
    "LUX": [SensorDef("lux", "Illuminance", _get("lux"), SensorDeviceClass.ILLUMINANCE, "lx", M)],
    "ACTIVE_POWER": [SensorDef("active_power", "Power", _get("activePower"),
        SensorDeviceClass.POWER, UnitOfPower.WATT, M)],
    "ACTIVE_CURRENT": [SensorDef("active_current", "Current", _get("activeCurrent"),
        SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, M)],
    "MEASURE_POWER": [
        SensorDef("total_energy", "Energy", _get("totalPower"), SensorDeviceClass.ENERGY,
                  UnitOfEnergy.KILO_WATT_HOUR, SensorStateClass.TOTAL_INCREASING),
        SensorDef("energy_today", "Energy today", _get("powerToday"), SensorDeviceClass.ENERGY,
                  UnitOfEnergy.KILO_WATT_HOUR, SensorStateClass.TOTAL),
        SensorDef("energy_yesterday", "Energy yesterday", _get("powerYesterday"),
                  SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, None, None, False),
    ],
    "PHASE_P": [SensorDef(f"phase_power_{i+1}", f"Phase {i+1} power", _phase("phaseP", i),
        SensorDeviceClass.POWER, UnitOfPower.WATT, M) for i in range(3)],
    "PHASE_I": [SensorDef(f"phase_current_{i+1}", f"Phase {i+1} current", _phase("phaseI", i),
        SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, M) for i in range(3)],
    "PHASE_U": [SensorDef(f"phase_voltage_{i+1}", f"Phase {i+1} voltage", _phase("phaseU", i),
        SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, M) for i in range(3)],
    "BATTERY_U": [SensorDef("battery_voltage", "Battery voltage", _get("batteryV"),
        SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, M, EntityCategory.DIAGNOSTIC)],
    "CONTROL_TEMPERATURE": [SensorDef("heating_demand", "Heating demand", _get("heatingDemand"),
        None, PERCENTAGE, M)],
}

CURATED_BINARY: dict[str, list[BinaryDef]] = {
    "MOTION": [BinaryDef("motion", "Motion", _get("motion"), BinarySensorDeviceClass.MOTION)],
    "CONTACT": [BinaryDef("contact", "Contact", _get("open"), BinarySensorDeviceClass.OPENING)],
    "MOISTURE": [BinaryDef("moisture", "Moisture", _get("moisture"), BinarySensorDeviceClass.MOISTURE)],
    "SMOKE": [BinaryDef("smoke", "Smoke", _get("alert"), BinarySensorDeviceClass.SMOKE)],
    "TWILIGHT": [BinaryDef("twilight", "Twilight", _get("twilight"), BinarySensorDeviceClass.LIGHT)],
    "SIREN": [BinaryDef("siren", "Siren", _get("sirenOn"), BinarySensorDeviceClass.SOUND)],
    "BATTERY_U": [BinaryDef("battery_low", "Battery low", _get("batteryLow"),
        BinarySensorDeviceClass.BATTERY, EntityCategory.DIAGNOSTIC)],
    "DEVICE": [BinaryDef("reachable", "Connectivity", _get("reachable"),
        BinarySensorDeviceClass.CONNECTIVITY, EntityCategory.DIAGNOSTIC)],
}

# Capabilities whose attributes are fully represented by curated entities.
CURATED_ATTRS: dict[str, set[str]] = {
    "TEMPERATURE": {"temperature"}, "HUMIDITY": {"humidity"}, "CO2": {"co2Ppm"},
    "PRESSURE": {"pressure"}, "LUX": {"lux"}, "ACTIVE_POWER": {"activePower"},
    "ACTIVE_CURRENT": {"activeCurrent"},
    "MEASURE_POWER": {"totalPower", "powerToday", "powerYesterday"},
    "PHASE_P": {"phaseP"}, "PHASE_I": {"phaseI"}, "PHASE_U": {"phaseU"},
    "BATTERY_U": {"batteryV", "batteryLow"}, "MOTION": {"motion"}, "CONTACT": {"open"},
    "MOISTURE": {"moisture"}, "SMOKE": {"alert"}, "TWILIGHT": {"twilight"}, "SIREN": {"sirenOn"},
    "DEVICE": {"reachable"}, "CONTROL_TEMPERATURE": {"targetTemp", "heatingDemand"},
    "GENERATE_ALERT": {"alert"}, "ON_OFF": {"isOn"}, "LIFT": {"liftPct"}, "TILT": {"tiltPct"},
    "COLOR_HS": {"hue", "saturation"}, "BRIGHTNESS": {"brightness"}, "COLOR_TEMP": {"temperature"},
    "TRANSITION": {"transitionMsec"}, "SHUTTER": {"motorStatus", "calibrating"},
}
