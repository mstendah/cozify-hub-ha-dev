import json

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.cozify_hub_dev.api import (
    AuthError,
    CannotConnect,
    CozifyCloud,
    HubClient,
    RemoteUnavailable,
    api_prefix,
    cloud_base_for_version,
    jwt_payload,
    token_expiry,
)

BASE = "https://cloud.test/ui/0.2"


def _client(hass, **kw):
    return HubClient(async_get_clientsession(hass), hub_id="h1", hub_key="HK", cloud_token="TOK",
                     cloud_base=BASE, **kw)


def test_helpers():
    assert api_prefix("1.14.12.20") == "1.14"
    assert cloud_base_for_version("1.14.9.3").startswith("https://api.cozify.fi")
    assert cloud_base_for_version("1.14.15.1").startswith("https://cloudapi.cozify.io")
    import base64
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 123, "hub_name": "X"}).encode()).decode().rstrip("=")
    tok = f"a.{payload}.c"
    assert token_expiry(tok) == 123.0 and jwt_payload(tok)["hub_name"] == "X"
    assert token_expiry("garbage") is None


async def test_login_flow(hass, aioclient_mock):
    aioclient_mock.post(f"{BASE}/user/requestlogin", text="")
    aioclient_mock.post(f"{BASE}/user/emaillogin", text='"abc.def.ghi"')
    aioclient_mock.get(f"{BASE}/user/hubkeys", json={"h1": "KEY"})
    cloud = CozifyCloud(async_get_clientsession(hass), BASE)
    await cloud.request_login_code("a@b.c")
    assert await cloud.login("a@b.c", "123456") == "abc.def.ghi"
    # the single-use code is sent as query params
    assert aioclient_mock.mock_calls[1][1].query == {"email": "a@b.c", "password": "123456"}
    assert await cloud.hub_keys("abc.def.ghi") == {"h1": "KEY"}


async def test_login_rejected(hass, aioclient_mock):
    aioclient_mock.post(f"{BASE}/user/emaillogin", status=401, text="nope")
    with pytest.raises(AuthError):
        await CozifyCloud(async_get_clientsession(hass), BASE).login("a@b.c", "x")


async def test_refresh_invalidates_old_token(hass, aioclient_mock):
    aioclient_mock.get(f"{BASE}/user/refreshsession", text="NEW")
    aioclient_mock.put(f"{BASE}/user/logout", text="")
    assert await CozifyCloud(async_get_clientsession(hass), BASE).refresh("OLD") == "NEW"
    assert aioclient_mock.mock_calls[1][3]["Authorization"] == "OLD"  # old token used for logout


async def test_local_first_then_cloud_fallback(hass, aioclient_mock):
    c = _client(hass, host="10.0.0.5")
    aioclient_mock.get("http://10.0.0.5:8893/hub", json={"hubId": "h1", "version": "1.14.12.20", "name": "N", "features": [2]})
    await c.bootstrap()
    assert c.is_local and c.api_prefix == "1.14" and c.features == [2]
    aioclient_mock.get("http://10.0.0.5:8893/cc/1.14/devices", json={"a": 1})
    assert await c.devices() == {"a": 1}
    assert aioclient_mock.mock_calls[-1][3]["Authorization"] == "HK"

    # LAN dies -> relay with cloud token + X-Hub-Key
    import aiohttp
    aioclient_mock.clear_requests()
    aioclient_mock.get("http://10.0.0.5:8893/cc/1.14/devices", exc=aiohttp.ClientError("down"))
    aioclient_mock.get(f"{BASE}/hub/remote/cc/1.14/devices", json={"b": 2})
    assert await c.devices() == {"b": 2}
    assert not c.is_local
    hdr = aioclient_mock.mock_calls[-1][3]
    assert hdr["Authorization"] == "TOK" and hdr["X-Hub-Key"] == "HK"


async def test_410_triggers_rebootstrap(hass, aioclient_mock):
    c = _client(hass)
    aioclient_mock.get(f"{BASE}/hub/remote/hub", json={"hubId": "h1", "version": "1.15.0.1", "features": []})
    c.version = "1.14.1.1"
    aioclient_mock.get(f"{BASE}/hub/remote/cc/1.14/devices", status=410)
    aioclient_mock.get(f"{BASE}/hub/remote/cc/1.15/devices", json={"ok": True})
    assert await c.devices() == {"ok": True}
    assert c.api_prefix == "1.15"


async def test_402_and_401(hass, aioclient_mock):
    c = _client(hass)
    c.version = "1.14.1.1"
    aioclient_mock.get(f"{BASE}/hub/remote/cc/1.14/devices", status=402)
    with pytest.raises(RemoteUnavailable):
        await c.devices()
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/hub/remote/cc/1.14/devices", status=401, text="x")
    with pytest.raises(AuthError):
        await c.devices()


async def test_no_route(hass):
    c = HubClient(async_get_clientsession(hass), hub_id="h", hub_key="k", cloud_token=None)
    c.version = "1.14.1.1"
    with pytest.raises(CannotConnect):
        await c.devices()
