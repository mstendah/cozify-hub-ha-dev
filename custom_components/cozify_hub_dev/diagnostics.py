"""Diagnostics with secrets redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import spec
from .const import CONF_CLOUD_TOKEN, CONF_EMAIL, CONF_HOST, CONF_HUB_KEY

TO_REDACT = {CONF_CLOUD_TOKEN, CONF_HUB_KEY, CONF_EMAIL, CONF_HOST, "cozify_uuid", "client_id", "email"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry) -> dict[str, Any]:
    c = entry.runtime_data
    unknown_caps: dict[str, int] = {}
    unsupported: dict[str, list[str]] = {}
    for dev in c.devices.values():
        caps = set((dev.get("capabilities") or {}).get("values", []))
        for cap in caps:
            if not spec.is_known_capability(cap):
                unknown_caps[cap] = unknown_caps.get(cap, 0) + 1
        if caps & {"AIRCON", "SHUTTER", "LIFT", "RECORD_VIDEO", "PLAY", "PLAY_VOLUME"}:
            unsupported.setdefault(str(dev.get("type")), []).append(str(dev.get("name")))
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "hub": {"version": c.client.version, "features": c.client.features, "local": c.client.is_local},
        "spec_revision": spec.docs_revision(),
        "counts": {
            "devices": len(c.devices),
            "rules": len(c.rules),
            "scenes": len(c.scenes),
            "rooms": len(c.rooms),
        },
        "capabilities_not_in_spec": unknown_caps,
        "device_types_without_dedicated_platform": unsupported,
        "devices": {
            k: {"type": v.get("type"), "model": v.get("model"),
                "capabilities": (v.get("capabilities") or {}).get("values"),
                "state_keys": sorted((v.get("state") or {}).keys())}
            for k, v in c.devices.items()
        },
    }
