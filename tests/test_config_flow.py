import base64
import json
import time
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cozify_hub.api import AuthError
from custom_components.cozify_hub.const import CONF_CLOUD_TOKEN, CONF_EMAIL, CONF_HUB_ID, DOMAIN

from .conftest import HUB_ID


def _jwt(**claims):
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"h.{body}.s"


CLOUD = "custom_components.cozify_hub.config_flow.CozifyCloud"
FLOW = "custom_components.cozify_hub.config_flow"


async def test_full_flow(hass):
    key = _jwt(hub_name="Office")
    with patch(CLOUD) as cloud_cls, patch(f"{FLOW}.find_local_host", AsyncMock(return_value="192.0.2.5")), \
         patch(f"{FLOW}.HubClient") as client_cls, patch("custom_components.cozify_hub.async_setup_entry", return_value=True):
        cloud = cloud_cls.return_value
        cloud.request_login_code = AsyncMock()
        cloud.login = AsyncMock(return_value="TOKEN")
        cloud.hub_keys = AsyncMock(return_value={HUB_ID: key})
        client = client_cls.return_value
        client.bootstrap = AsyncMock(return_value={"name": "Office Hub", "hubId": HUB_ID})
        client.cloud_base = "https://api.cozify.fi/ui/0.2"

        r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        assert r["step_id"] == "user"
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_EMAIL: "A@Example.com"})
        assert r["step_id"] == "code"
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"code": "123456"})
        assert r["type"] == FlowResultType.CREATE_ENTRY
        assert r["title"] == "Office Hub"
        assert r["data"][CONF_HUB_ID] == HUB_ID and r["data"]["host"] == "192.0.2.5"
        assert r["data"][CONF_EMAIL] == "a@example.com"
        cloud.login.assert_awaited_once_with("a@example.com", "123456")


async def test_invalid_code(hass):
    with patch(CLOUD) as cloud_cls:
        cloud = cloud_cls.return_value
        cloud.request_login_code = AsyncMock()
        cloud.login = AsyncMock(side_effect=AuthError("x"))
        r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_EMAIL: "a@b.c"})
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"code": "bad"})
        assert r["type"] == FlowResultType.FORM and r["errors"] == {"base": "invalid_code"}


async def test_existing_token_skips_code(hass):
    """A second hub on the same account must not need another single-use code."""
    exp = int(time.time()) + 20 * 24 * 3600
    MockConfigEntry(domain=DOMAIN, unique_id="other-hub",
                    data={CONF_EMAIL: "a@b.c", CONF_CLOUD_TOKEN: _jwt(exp=exp), CONF_HUB_ID: "other-hub"}).add_to_hass(hass)
    with patch(CLOUD) as cloud_cls:
        cloud = cloud_cls.return_value
        cloud.request_login_code = AsyncMock()
        cloud.hub_keys = AsyncMock(return_value={"other-hub": _jwt(), HUB_ID: _jwt(hub_name="Second")})
        cloud.lan_ips = AsyncMock(return_value=[])
        with patch(f"{FLOW}.find_local_host", AsyncMock(return_value=None)), patch(f"{FLOW}.HubClient") as client_cls, \
             patch("custom_components.cozify_hub.async_setup_entry", return_value=True):
            client_cls.return_value.bootstrap = AsyncMock(return_value={"name": "Second"})
            client_cls.return_value.cloud_base = "x"
            r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
            r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_EMAIL: "a@b.c"})
            cloud.request_login_code.assert_not_awaited()
            assert r["type"] == FlowResultType.CREATE_ENTRY and r["data"][CONF_HUB_ID] == HUB_ID


async def test_options_flow(hass, entry, fake_hub):
    assert await hass.config_entries.async_setup(entry.entry_id)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"host": " 192.0.2.99 ", "prefer_local": False})
    assert r["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options == {"host": "192.0.2.99", "prefer_local": False}
