from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.cozify_hub_dev.const import DOMAIN, EVENT_DOORBELL

from .conftest import CO2, DOORBELL, LIGHT, RULE, SOCKET, THERMO


def _ent(hass, platform, suffix):
    reg = er.async_get(hass)
    for e in reg.entities.values():
        if e.platform == DOMAIN and e.domain == platform and e.unique_id.endswith(suffix):
            return e.entity_id
    raise AssertionError(f"{platform} {suffix} not found: {[x.unique_id for x in reg.entities.values()]}")


async def test_entities_created(hass: HomeAssistant, setup):
    assert hass.states.get(_ent(hass, "light", f"{LIGHT}_light")).state == "off"
    co2 = hass.states.get(_ent(hass, "sensor", f"{CO2}_co2"))
    assert co2.state == "470"
    assert co2.attributes["unit_of_measurement"] == "ppm"
    assert hass.states.get(_ent(hass, "sensor", f"{CO2}_temperature")).state == "21.8"
    assert hass.states.get(_ent(hass, "switch", f"{SOCKET}_switch")).state == "on"
    assert hass.states.get(_ent(hass, "sensor", f"{SOCKET}_active_power")).state == "0.0"
    assert hass.states.get(_ent(hass, "switch", f"rule_{RULE}")).state == "on"
    assert hass.states.get(_ent(hass, "scene", "scene_30000000-0000-4000-8000-000000000001"))
    assert hass.states.get(_ent(hass, "climate", f"{THERMO}_climate")).attributes["temperature"] == 22.0
    assert hass.states.get(_ent(hass, "event", f"{DOORBELL}_alert_event"))
    # Lights must not get a bogus temperature sensor from the colour-temperature field.
    reg = er.async_get(hass)
    assert not [e for e in reg.entities.values() if e.unique_id.endswith(f"{LIGHT}_temperature")]


async def test_light_color_command(hass: HomeAssistant, setup):
    eid = _ent(hass, "light", f"{LIGHT}_light")
    await hass.services.async_call("light", "turn_on",
        {"entity_id": eid, "hs_color": [120, 100], "brightness": 255, "transition": 0}, blocking=True)
    cmd = setup.commands()[-1][0]
    assert cmd["type"] == "CMD_DEVICE" and cmd["id"] == LIGHT
    st = cmd["state"]
    assert st["colorMode"] == "hs" and abs(st["hue"] - 2.0944) < 1e-3 and st["saturation"] == 1.0
    assert st["transitionMsec"] == 0 and st["brightness"] == 1.0
    assert hass.states.get(eid).state == "on"


async def test_switch_and_thermostat_commands(hass: HomeAssistant, setup):
    sw = _ent(hass, "switch", f"{SOCKET}_switch")
    await hass.services.async_call("switch", "turn_off", {"entity_id": sw}, blocking=True)
    assert setup.commands()[-1] == [{"type": "CMD_DEVICE_OFF", "id": SOCKET}]
    th = _ent(hass, "climate", f"{THERMO}_climate")
    await hass.services.async_call("climate", "set_temperature", {"entity_id": th, "temperature": 23}, blocking=True)
    assert setup.commands()[-1][0]["state"] == {"type": "STATE_THERMOSTAT", "targetTemp": 23.0}


async def test_rule_switch_calls_hub(hass: HomeAssistant, setup):
    eid = _ent(hass, "switch", f"rule_{RULE}")
    await hass.services.async_call("switch", "turn_off", {"entity_id": eid}, blocking=True)
    assert ("PUT", "/rules/command", [{"type": "RULE_OFF_COMMAND", "id": RULE}], None) in setup.calls
    assert hass.states.get(eid).state == "off"


async def test_scene_activation(hass: HomeAssistant, setup):
    eid = _ent(hass, "scene", "scene_30000000-0000-4000-8000-000000000001")
    await hass.services.async_call("scene", "turn_on", {"entity_id": eid}, blocking=True)
    assert any(c[1] == "/scenes/command" for c in setup.calls)


async def test_delta_updates_state_and_doorbell_event(hass: HomeAssistant, setup):
    events = []
    hass.bus.async_listen(EVENT_DOORBELL, lambda e: events.append(e.data))
    setup.push_device_delta(CO2, {"co2Ppm": 999})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    assert hass.states.get(_ent(hass, "sensor", f"{CO2}_co2")).state == "999"
    # doorbell press: alert true and lastSeen advances
    setup.push_device_delta(DOORBELL, {"alert": True, "lastSeen": 9_999_999_999_999})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
    await hass.async_block_till_done()
    assert events and events[-1]["device_id"] == DOORBELL
    assert hass.states.get(_ent(hass, "event", f"{DOORBELL}_alert_event")).attributes["event_type"] == "pressed"


async def test_unreachable_device_unavailable(hass: HomeAssistant, setup):
    setup.push_device_delta(CO2, {"reachable": False})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    assert hass.states.get(_ent(hass, "sensor", f"{CO2}_co2")).state == "unavailable"


async def test_unknown_capability_gets_generic_entity(hass, setup):
    """A documented attribute without curated mapping still shows up (disabled, diagnostic)."""
    reg = er.async_get(hass)
    generic = [e for e in reg.entities.values() if "_x_" in e.unique_id]
    assert generic, "spec-driven fallback entities expected (e.g. upgradeStatus)"
    assert all(e.disabled_by is not None for e in generic)
    assert all(e.entity_category is not None for e in generic)


async def test_generic_defs_follow_spec(hass, setup):
    """Adding a documented capability to a device creates a fallback sensor for its attribute."""
    from custom_components.cozify_hub_dev.sensor import _sensor_defs_for

    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    dev = coordinator.devices[CO2]
    dev["capabilities"]["values"].append("LUX")
    dev["capabilities"]["values"].append("SELF_MOTION")
    dev["state"]["motionLevel"] = 0.3
    keys = {d.key for d in _sensor_defs_for(coordinator, CO2)}
    assert "lux" in keys  # curated
    assert "x_motionLevel" in keys  # spec-driven fallback, no curated mapping
