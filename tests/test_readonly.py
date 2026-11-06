"""Read-only mode: nothing may ever be written to the hub."""
import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.cozify_hub_dev.api import HubClient, ReadOnlyError
from custom_components.cozify_hub_dev.const import DOMAIN

from .conftest import HUB_ID, LIGHT, RULE, SOCKET, THERMO

WRITES = ("PUT", "POST", "DELETE", "PATCH")


def _domains(hass):
    reg = er.async_get(hass)
    return {e.domain for e in reg.entities.values() if e.platform == DOMAIN}


def _find(hass, domain, suffix):
    reg = er.async_get(hass)
    for e in reg.entities.values():
        if e.platform == DOMAIN and e.domain == domain and e.unique_id.endswith(suffix):
            return e.entity_id
    return None


@pytest.mark.parametrize(
    "method,path,blocked",
    [
        ("GET", "/devices", False),
        ("GET", "/hub/poll", False),
        ("POST", "/rules/proposals", False),  # read-only query despite the verb
        ("PUT", "/devices/command", True),
        ("PUT", "/rules/command", True),
        ("PUT", "/rules", True),
        ("POST", "/rules/template", True),
        ("DELETE", "/rules", True),
        ("PUT", "/scenes/command", True),
        ("put", "/anything/new", True),
    ],
)
def test_guard(method, path, blocked):
    c = HubClient(None, hub_id="h", hub_key="k", read_only=True)
    if blocked:
        with pytest.raises(ReadOnlyError):
            c._guard(method, path)
    else:
        c._guard(method, path)
    # a normal client never blocks
    HubClient(None, hub_id="h", hub_key="k")._guard(method, path)


async def test_guard_in_real_transport(hass, aioclient_mock):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    c = HubClient(async_get_clientsession(hass), hub_id="h", hub_key="k", host="192.0.2.1", read_only=True)
    with pytest.raises(ReadOnlyError):
        await c.device_command([{"type": "CMD_DEVICE_ON", "id": "x"}])
    with pytest.raises(ReadOnlyError):
        await c._call_once("PUT", "/devices/command", [], None)  # even bypassing call()
    assert aioclient_mock.call_count == 0


async def test_no_controllable_entities(hass, ro_setup):
    assert _domains(hass) <= {"sensor", "binary_sensor", "event"}
    assert _find(hass, "binary_sensor", f"{SOCKET}_power")
    assert _find(hass, "binary_sensor", f"{LIGHT}_power")
    assert _find(hass, "binary_sensor", f"rule_state_{RULE}")
    assert _find(hass, "sensor", f"{THERMO}_target_temperature")
    assert hass.states.get(_find(hass, "binary_sensor", f"rule_state_{RULE}")).state == "on"
    assert hass.states.get(_find(hass, "sensor", f"{THERMO}_target_temperature")).state == "22.0"
    assert hass.states.get(_find(hass, "binary_sensor", f"{SOCKET}_power")).state == "on"


async def test_services_cannot_write(hass, ro_setup):
    for name, data in [
        ("set_rule_state", {"rule": "coffee watcher", "state": "off"}),
        ("run_scene", {"scene": "Evening"}),
        ("delete_rule", {"rule": "Coffee watcher", "confirm": True}),
        ("send_command", {"commands": [{"type": "CMD_DEVICE_OFF", "id": SOCKET}]}),
    ]:
        with pytest.raises((HomeAssistantError, ServiceValidationError)):
            await hass.services.async_call(DOMAIN, name, data, blocking=True)
    assert not [c for c in ro_setup.calls if c[0] in WRITES]
    assert ro_setup.rules_data[RULE]["is_on"] is True


async def test_reads_still_work(hass, ro_setup):
    log = await hass.services.async_call(DOMAIN, "get_rule_log", {}, blocking=True, return_response=True)
    assert log["log"]
    await hass.services.async_call(
        DOMAIN, "get_rule_proposals", {"device_ids": [SOCKET]}, blocking=True, return_response=True
    )


async def test_default_mode_unchanged(hass, setup):
    # entries created before the option existed keep full control
    assert {"light", "switch", "climate", "scene"} <= _domains(hass)


async def test_setup_flow_offers_read_only(hass):
    from unittest.mock import AsyncMock, patch

    from homeassistant.config_entries import SOURCE_USER
    from homeassistant.data_entry_flow import FlowResultType

    from .test_config_flow import CLOUD, FLOW, _jwt

    with patch(CLOUD) as cloud_cls, patch(f"{FLOW}.find_local_host", AsyncMock(return_value=None)), \
         patch(f"{FLOW}.HubClient") as client_cls, patch("custom_components.cozify_hub_dev.async_setup_entry", return_value=True):
        cloud = cloud_cls.return_value
        cloud.request_login_code = AsyncMock()
        cloud.login = AsyncMock(return_value="TOKEN")
        cloud.hub_keys = AsyncMock(return_value={HUB_ID: _jwt(hub_name="Office")})
        client_cls.return_value.bootstrap = AsyncMock(return_value={"name": "Office", "hubId": HUB_ID})
        client_cls.return_value.cloud_base = "https://api.cozify.fi/ui/0.2"
        r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"email": "a@example.com"})
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"code": "1"})
        assert r["step_id"] == "mode"
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"read_only": True})
        assert r["type"] == FlowResultType.CREATE_ENTRY
        assert r["options"] == {"read_only": True}
