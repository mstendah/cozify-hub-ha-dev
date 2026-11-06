"""Polling coordinator that keeps a local mirror of the hub model."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ApiError,
    AuthError,
    CannotConnect,
    CozifyCloud,
    CozifyError,
    HubClient,
    RemoteUnavailable,
    token_expiry,
)
from .const import (
    CONF_CLOUD_TOKEN,
    DOMAIN,
    EVENT_DOORBELL,
    POLL_INTERVAL_LOCAL,
    POLL_INTERVAL_REMOTE,
    SIGNAL_NEW_DEVICES,
    TOKEN_REFRESH_MARGIN_S,
)

_LOGGER = logging.getLogger(__name__)

# Delta type -> attribute on the coordinator
DELTA_COLLECTIONS = {
    "DEVICE_DELTA": ("devices", "devices"),
    "GROUP_DELTA": ("groups", "groups"),
    "SCENE_DELTA": ("scenes", "scenes"),
    "RULE_DELTA": ("rules", "rules"),
    "ROOM_DELTA": ("rooms", "rooms"),
    "USER_DELTA": ("users", "users"),
    "ALARM_DELTA": ("alarms", "alarms"),
}

META_REFRESH_S = 300


class CozifyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Mirror of the hub: devices, rooms, scenes, rules, groups."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HubClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Cozify Hub {client.hub_id}",
            update_interval=timedelta(seconds=POLL_INTERVAL_REMOTE),
        )
        self.client = client
        self.devices: dict[str, dict[str, Any]] = {}
        self.groups: dict[str, dict[str, Any]] = {}
        self.scenes: dict[str, dict[str, Any]] = {}
        self.rules: dict[str, dict[str, Any]] = {}
        self.rooms: dict[str, dict[str, Any]] = {}
        self.users: dict[str, dict[str, Any]] = {}
        self.alarms: dict[str, dict[str, Any]] = {}
        self._ts = 0
        self._known_devices: set[str] = set()
        self._last_alert: dict[str, int] = {}
        self._meta_checked = 0.0
        self.loaded_platforms: list = []
        self.hub_meta: dict[str, Any] = {}

    # -- polling -----------------------------------------------------------
    async def _async_update_data(self) -> dict[str, Any]:
        await self._maybe_refresh_token()
        try:
            if self.client.version is None or time.monotonic() - self._meta_checked > META_REFRESH_S:
                self.hub_meta = await self.client.bootstrap()
                self._meta_checked = time.monotonic()
            delta = await self.client.poll(self._ts)
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except RemoteUnavailable as err:
            raise UpdateFailed(f"Remote access is not enabled for this hub: {err}") from err
        except (CannotConnect, ApiError) as err:
            raise UpdateFailed(str(err)) from err
        except CozifyError as err:
            raise UpdateFailed(str(err)) from err

        self._apply_delta(delta)
        self.update_interval = timedelta(
            seconds=POLL_INTERVAL_LOCAL if self.client.is_local else POLL_INTERVAL_REMOTE
        )
        return {"timestamp": self._ts}

    def _apply_delta(self, delta: dict[str, Any]) -> None:
        full = bool(delta.get("full"))
        ts = delta.get("timestamp")
        if isinstance(ts, int):
            self._ts = ts
        previous_states = {k: dict(v.get("state") or {}) for k, v in self.devices.items()}
        for item in delta.get("polls", []):
            mapping = DELTA_COLLECTIONS.get(item.get("type"))
            if mapping is None:
                _LOGGER.debug("Ignoring unknown delta type %s", item.get("type"))
                continue
            payload_key, attr = mapping
            store: dict[str, dict[str, Any]] = getattr(self, attr)
            if full:
                store.clear()  # a full delta replaces the categories it contains
            for obj_id, obj in (item.get(payload_key) or {}).items():
                if obj is None:
                    store.pop(obj_id, None)
                    continue
                if attr == "devices" and obj_id in store:
                    merged = {**store[obj_id], **obj}
                    if isinstance(obj.get("state"), dict):
                        merged["state"] = {**store[obj_id].get("state", {}), **obj["state"]}
                    store[obj_id] = merged
                else:
                    store[obj_id] = obj
        self._detect_events(previous_states)
        self._announce_new_devices()

    def _detect_events(self, previous: dict[str, dict[str, Any]]) -> None:
        """Fire HA bus events for alert style devices (doorbells, smoke ...)."""
        for dev_id, dev in self.devices.items():
            caps = (dev.get("capabilities") or {}).get("values", [])
            if "GENERATE_ALERT" not in caps:
                continue
            state = dev.get("state") or {}
            marker = max(
                int(state.get("alertAt") or 0),
                int(state.get("alertStartAt") or 0),
                int(state.get("lastSeen") or 0) if state.get("alert") else 0,
            )
            last = self._last_alert.get(dev_id)
            self._last_alert[dev_id] = marker
            if last is None:
                continue  # first sight: don't fire for stale alerts
            if state.get("alert") and marker > last:
                self.hass.bus.async_fire(
                    EVENT_DOORBELL,
                    {
                        "hub_id": self.client.hub_id,
                        "device_id": dev_id,
                        "name": dev.get("name"),
                        "type": "alert",
                        "timestamp": marker,
                    },
                )
                async_dispatcher_send(
                    self.hass, f"{DOMAIN}_alert_{self.client.hub_id}_{dev_id}", marker
                )

    def _announce_new_devices(self) -> None:
        new = set(self.devices) - self._known_devices
        if new and self._known_devices:
            async_dispatcher_send(self.hass, SIGNAL_NEW_DEVICES.format(self.client.hub_id), new)
        self._known_devices |= new

    # -- token upkeep ------------------------------------------------------
    async def _maybe_refresh_token(self) -> None:
        token = self.client.cloud_token
        if not token:
            return
        exp = token_expiry(token)
        if exp is None or exp - time.time() > TOKEN_REFRESH_MARGIN_S:
            return
        cloud = CozifyCloud(self.client._session, self.client.cloud_base)  # noqa: SLF001
        try:
            new = await cloud.refresh(token)
        except AuthError:
            _LOGGER.warning("Cozify cloud token expired; re-authentication needed")
            if not self.client.is_local:
                raise ConfigEntryAuthFailed("cloud token expired") from None
            return
        except CozifyError as err:
            _LOGGER.debug("Token refresh failed: %s", err)
            return
        self.client.cloud_token = new
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**self.config_entry.data, CONF_CLOUD_TOKEN: new}
        )

    # -- helpers -----------------------------------------------------------
    def room_name(self, device: dict[str, Any]) -> str | None:
        rooms = device.get("room") or []
        if rooms and rooms[0] in self.rooms:
            return self.rooms[rooms[0]].get("name")
        return None

    def capabilities(self, device_id: str) -> set[str]:
        dev = self.devices.get(device_id, {})
        return set((dev.get("capabilities") or {}).get("values", []))

    async def async_send(self, commands: list[dict[str, Any]], optimistic: dict[str, dict] | None = None) -> None:
        """Send device commands and optionally patch local state at once."""
        await self.client.device_command(commands)
        if optimistic:
            for dev_id, patch in optimistic.items():
                if dev_id in self.devices:
                    state = self.devices[dev_id].setdefault("state", {})
                    state.update(patch)
            self.async_update_listeners()
