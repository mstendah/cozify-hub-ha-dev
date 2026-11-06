"""Async client for the Cozify cloud and Cozify Hub API.

Only the transport, authentication and typed convenience wrappers live here.
Which endpoints exist is described by ``api_spec.json`` (generated from the
official API documentation by ``tools/sync_api_docs.py``); the generic
:meth:`HubClient.call` can reach any documented endpoint so new API features
are usable before a dedicated wrapper is written.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import aiohttp

from .const import CLOUD_BASES, LOCAL_PORT

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)


class CozifyError(Exception):
    """Base error."""


class AuthError(CozifyError):
    """Credentials rejected (401/403)."""


class RemoteUnavailable(CozifyError):
    """Hub reached through the cloud, but remote access is not enabled (402)."""


class CannotConnect(CozifyError):
    """Network level failure."""


class ApiError(CozifyError):
    """Unexpected HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def jwt_payload(token: str) -> dict[str, Any]:
    """Decode (without verifying) the payload of a JWT-like token."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - tokens are opaque to us
        return {}


def token_expiry(token: str) -> float | None:
    """Return the ``exp`` claim of a JWT-like token, or None."""
    exp = jwt_payload(token).get("exp")
    try:
        return float(exp) if exp is not None else None
    except (TypeError, ValueError):
        return None


def api_prefix(hub_version: str) -> str:
    """'1.14.12.20' -> '1.14' (first two components, see docs section 3.3)."""
    return ".".join(hub_version.split(".")[:2])


def cloud_base_for_version(hub_version: str | None) -> str:
    """Pick the cloud base for a hub software version."""
    if hub_version and hub_version.startswith("1.14.9."):
        return CLOUD_BASES[0]
    return CLOUD_BASES[1] if hub_version else CLOUD_BASES[0]


class CozifyCloud:
    """Account level cloud calls (login, hub keys, LAN lookup)."""

    def __init__(self, session: aiohttp.ClientSession, base: str = CLOUD_BASES[0]) -> None:
        self._session = session
        self.base = base

    async def _req(self, method: str, path: str, *, token: str | None = None, **kw: Any) -> Any:
        headers = {"Authorization": token} if token else {}
        try:
            async with self._session.request(
                method, f"{self.base}{path}", headers=headers, timeout=REQUEST_TIMEOUT, **kw
            ) as resp:
                text = await resp.text()
                if resp.status in (401, 403):
                    raise AuthError(text or "unauthorized")
                if resp.status >= 400:
                    raise ApiError(resp.status, text[:200])
                return text
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CannotConnect(str(err)) from err

    async def request_login_code(self, email: str) -> None:
        """Ask the cloud to email a one-time code."""
        await self._req("POST", "/user/requestlogin", params={"email": email})

    async def login(self, email: str, code: str) -> str:
        """Exchange the one-time code for a cloud token.

        The code is single use: never call this twice with the same code.
        """
        text = await self._req("POST", "/user/emaillogin", params={"email": email, "password": code})
        token = text.strip().strip('"')
        if not token or token.startswith("{"):
            raise AuthError("login failed")
        return token

    async def refresh(self, token: str) -> str:
        """Refresh a cloud token and invalidate the old one (docs 2.3)."""
        new = (await self._req("GET", "/user/refreshsession", token=token)).strip().strip('"')
        if not new or new.startswith("{"):
            raise AuthError("refresh failed")
        try:
            await self._req("PUT", "/user/logout", token=token)
        except CozifyError as err:  # the new token is already valid
            _LOGGER.debug("Could not invalidate old token: %s", err)
        return new

    async def hub_keys(self, token: str) -> dict[str, str]:
        """Return ``{hub_id: hub_key}`` for the account."""
        return json.loads(await self._req("GET", "/user/hubkeys", token=token))

    async def lan_ips(self, token: str) -> list[str]:
        """Cloud assisted LAN discovery (docs 3.1)."""
        try:
            return json.loads(await self._req("GET", "/hub/lan_ip", token=token))
        except (CozifyError, ValueError):
            return []


class HubClient:
    """Client for one hub. Prefers LAN, falls back to the cloud relay."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        hub_id: str,
        hub_key: str,
        cloud_token: str | None = None,
        cloud_base: str = CLOUD_BASES[0],
        host: str | None = None,
        prefer_local: bool = True,
        client_id: str = "home-assistant",
    ) -> None:
        self._session = session
        self.hub_id = hub_id
        self.hub_key = hub_key
        self.cloud_token = cloud_token
        self.cloud_base = cloud_base
        self.host = host
        self.prefer_local = prefer_local
        self.client_id = client_id
        self.version: str | None = None
        self.features: list[int] = []
        self.name: str | None = None
        self.local_ok = False
        self._local_fail_until = 0.0

    # -- transport ---------------------------------------------------------
    @property
    def api_prefix(self) -> str:
        return api_prefix(self.version) if self.version else "1.14"

    @property
    def is_local(self) -> bool:
        return self.local_ok

    async def _http(
        self, method: str, url: str, headers: dict[str, str], json_body: Any, params: dict | None
    ) -> Any:
        try:
            async with self._session.request(
                method, url, headers=headers, json=json_body, params=params, timeout=REQUEST_TIMEOUT
            ) as resp:
                text = await resp.text()
                if resp.status in (401, 403):
                    raise AuthError(text[:200] or "unauthorized")
                if resp.status == 402:
                    raise RemoteUnavailable("remote access not enabled for this hub")
                if resp.status == 410:
                    raise ApiError(410, "api version gone")
                if resp.status >= 400:
                    raise ApiError(resp.status, text[:200])
                if not text.strip():
                    return None
                try:
                    return json.loads(text)
                except ValueError:
                    return text
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CannotConnect(str(err)) from err

    def _local_url(self, path: str) -> str:
        return f"http://{self.host}:{LOCAL_PORT}/cc/{self.api_prefix}{path}"

    def _remote_url(self, path: str) -> str:
        return f"{self.cloud_base}/hub/remote/cc/{self.api_prefix}{path}"

    async def call(
        self, method: str, path: str, *, json_body: Any = None, params: dict | None = None
    ) -> Any:
        """Call any documented hub endpoint (path relative to ``/cc/<ver>``)."""
        for attempt in (0, 1):
            try:
                return await self._call_once(method, path, json_body, params)
            except ApiError as err:
                if err.status == 410 and attempt == 0:
                    await self.bootstrap()
                    continue
                raise
        raise CozifyError("unreachable")  # pragma: no cover

    async def _call_once(self, method: str, path: str, json_body: Any, params: dict | None) -> Any:
        use_local = bool(self.host) and self.prefer_local and time.monotonic() >= self._local_fail_until
        if use_local:
            try:
                result = await self._http(
                    method, self._local_url(path), {"Authorization": self.hub_key}, json_body, params
                )
                self.local_ok = True
                return result
            except CannotConnect:
                self.local_ok = False
                self._local_fail_until = time.monotonic() + 60
                _LOGGER.debug("Local hub %s unreachable, using cloud relay", self.host)
        if not self.cloud_token:
            raise CannotConnect("hub unreachable locally and no cloud token available")
        self.local_ok = False
        return await self._http(
            method,
            self._remote_url(path),
            {"Authorization": self.cloud_token, "X-Hub-Key": self.hub_key},
            json_body,
            params,
        )

    # -- bootstrap ---------------------------------------------------------
    async def bootstrap(self) -> dict[str, Any]:
        """Read hub metadata (docs 3.2) and derive the API prefix."""
        meta: Any = None
        if self.host and self.prefer_local:
            try:
                meta = await self._http("GET", f"http://{self.host}:{LOCAL_PORT}/hub", {}, None, None)
                self.local_ok = True
            except CozifyError:
                self.local_ok = False
        if meta is None:
            if not self.cloud_token:
                raise CannotConnect("no route to hub")
            meta = None
            last: CozifyError | None = None
            for base in dict.fromkeys([self.cloud_base, *CLOUD_BASES]):
                try:
                    meta = await self._http(
                        "GET",
                        f"{base}/hub/remote/hub",
                        {"Authorization": self.cloud_token, "X-Hub-Key": self.hub_key},
                        None,
                        None,
                    )
                    self.cloud_base = base
                    break
                except RemoteUnavailable:
                    raise
                except CozifyError as err:
                    last = err
            if meta is None:
                raise last or CannotConnect("bootstrap failed")
        self.version = meta.get("version")
        self.features = list(meta.get("features", []))
        self.name = meta.get("name")
        if meta.get("hubId") and meta["hubId"] != self.hub_id:
            raise CozifyError("hub id mismatch")
        return meta

    # -- typed helpers -----------------------------------------------------
    async def poll(self, ts: int = 0) -> dict[str, Any]:
        return await self.call("GET", "/hub/poll", params={"ts": ts, "cozify_uuid": self.client_id})

    async def devices(self) -> dict[str, Any]:
        return await self.call("GET", "/devices")

    async def rooms(self) -> dict[str, Any]:
        return await self.call("GET", "/rooms")

    async def device_command(self, commands: list[dict[str, Any]]) -> None:
        await self.call("PUT", "/devices/command", json_body=commands)

    async def scenes(self) -> dict[str, Any]:
        return await self.call("GET", "/scenes")

    async def scene_command(self, scene_id: str, on: bool) -> None:
        await self.call(
            "PUT",
            "/scenes/command",
            json_body=[{"type": "CMD_SCENE_ON" if on else "CMD_SCENE_OFF", "id": scene_id}],
        )

    async def rules(self) -> dict[str, Any]:
        return await self.call("GET", "/rules")

    async def rule_command(self, rule_id: str, on: bool) -> None:
        await self.call(
            "PUT",
            "/rules/command",
            json_body=[{"type": "RULE_ON_COMMAND" if on else "RULE_OFF_COMMAND", "id": rule_id}],
        )

    async def delete_rule(self, rule_id: str) -> None:
        await self.call("DELETE", "/rules", params={"ruleId": rule_id})

    async def rule_templates(self) -> Any:
        return await self.call("GET", "/rules/templates")

    async def rule_template_source(self, rule_type: str) -> Any:
        return await self.call("GET", "/rules/template", params={"ruleType": rule_type})

    async def install_rule_template(self, source: str) -> Any:
        """Install a custom rule. Re-posting an existing type DELETES its instances."""
        return await self.call("POST", "/rules/template", params={"ruleLogic": source})

    async def rule_log(self, rule_type: str | None = None) -> Any:
        params = {"ruleType": rule_type} if rule_type else None
        return await self.call("GET", "/rules/log", params=params)

    async def rule_proposals(self, device_ids: list[str], room: str | None, max_num: int = 5) -> Any:
        cmd: dict[str, Any] = {"type": "CMD_GET_PROPOSALS", "deviceIds": device_ids, "maxNum": max_num}
        if room:
            cmd["room"] = room
        return await self.call("POST", "/rules/proposals", json_body=[cmd])

    async def save_rule(self, config: dict[str, Any], on_config: dict[str, Any] | None = None) -> Any:
        body = {
            "rules": [config],
            "onConfiguration": on_config or {"type": "RULE_ON_CFG", "scenes": [], "timers": []},
        }
        return await self.call("PUT", "/rules", json_body=body)


async def find_local_host(
    session: aiohttp.ClientSession, cloud: CozifyCloud, token: str, hub_id: str
) -> str | None:
    """Use the cloud assisted LAN lookup and confirm which address is this hub."""
    for ip in await cloud.lan_ips(token):
        try:
            async with session.get(
                f"http://{ip}:{LOCAL_PORT}/hub", timeout=aiohttp.ClientTimeout(total=4)
            ) as resp:
                if resp.status == 200 and (await resp.json(content_type=None)).get("hubId") == hub_id:
                    return ip
        except (TimeoutError, aiohttp.ClientError, ValueError):
            continue
    return None
