"""Shared fixtures: a fake hub client that serves anonymised fixture data."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cozify_hub.api import HubClient
from custom_components.cozify_hub.const import (
    CONF_CLOUD_BASE,
    CONF_CLOUD_TOKEN,
    CONF_EMAIL,
    CONF_HOST,
    CONF_HUB_ID,
    CONF_HUB_KEY,
    DOMAIN,
)

FIX = Path(__file__).parent / "fixtures"
HUB_ID = "99999999-0000-4000-8000-000000000000"
_NAMES = {d["name"]: i for i, d in json.loads((FIX / "devices.json").read_text()).items()}
LIGHT = _NAMES["Desk lamp"]
CO2 = _NAMES["Air quality sensor"]
SOCKET = _NAMES["Coffee machine plug"]
DOORBELL = _NAMES["Doorbell"]
THERMO = _NAMES["Hall thermostat"]
RULE = "20000000-0000-4000-8000-000000000001"
SCENE = "30000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeHub(HubClient):
    """HubClient whose transport is replaced by in-memory fixtures."""

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        misc = json.loads((FIX / "hub_misc.json").read_text())
        self.devices_data = json.loads((FIX / "devices.json").read_text())
        self.rules_data = misc["rules"]
        self.scenes_data = misc["scenes"]
        self.rooms_data = misc["rooms"]
        self.calls: list[tuple] = []
        self.ts = 1000
        self.pending: list[dict] = []
        self.templates: Any = [{"type": "AUTO_LIGHT_RULE", "name": "Auto light"}]
        self.proposals: Any = []
        self.local_ok = True
        self.version = "1.14.12.20"
        self.features = [2]
        self.name = "Test Hub"

    async def bootstrap(self) -> dict[str, Any]:
        return {"hubId": self.hub_id, "name": "Test Hub", "version": "1.14.12.20", "features": [2]}

    async def call(self, method: str, path: str, *, json_body: Any = None, params: dict | None = None) -> Any:
        self.calls.append((method, path, json_body, params))
        if path == "/hub/poll":
            polls = []
            if params and params.get("ts") == 0:
                polls = [
                    {"type": "DEVICE_DELTA", "devices": copy.deepcopy(self.devices_data)},
                    {"type": "RULE_DELTA", "rules": copy.deepcopy(self.rules_data)},
                    {"type": "SCENE_DELTA", "scenes": copy.deepcopy(self.scenes_data)},
                    {"type": "ROOM_DELTA", "rooms": copy.deepcopy(self.rooms_data)},
                ]
                full = True
            else:
                polls, self.pending = self.pending, []
                full = False
            self.ts += 1
            return {"type": "POLL_DELTA", "timestamp": self.ts, "full": full, "polls": polls}
        if path == "/rules" and method == "GET":
            return copy.deepcopy(self.rules_data)
        if path == "/rules" and method == "PUT":
            cfg = json_body["rules"][0]
            self._seq = getattr(self, "_seq", 100) + 1
            rid = f"20000000-0000-4000-8000-{self._seq:012d}"
            self.rules_data[rid] = {"type": "RULE", "id": rid, "is_on": True, "scenes": {}, "timers": json_body["onConfiguration"]["timers"],
                                    "config": {**cfg, "id": rid}}
            return None
        if path == "/rules/template" and method == "POST":
            rtype = params["ruleLogic"].split("type = '")[1].split("'")[0]
            # real hub behaviour: reinstalling deletes the instances
            self.rules_data = {k: v for k, v in self.rules_data.items() if v["config"]["configType"] != rtype}
            return rtype
        if path == "/rules/templates":
            return self.templates
        if path == "/rules/proposals":
            return self.proposals
        if path == "/rules/log":
            return '[{"msg":"hello"}]'
        if path == "/rules/command":
            for cmd in json_body:
                if cmd["id"] in self.rules_data:
                    self.rules_data[cmd["id"]]["is_on"] = cmd["type"] == "RULE_ON_COMMAND"
            return None
        if path == "/rules" and method == "DELETE":
            self.rules_data.pop(params["ruleId"], None)
            return None
        return None

    def push_device_delta(self, dev_id: str, state: dict[str, Any]) -> None:
        self.pending.append({"type": "DEVICE_DELTA", "devices": {dev_id: {"state": state}}})

    def commands(self) -> list[Any]:
        return [c[2] for c in self.calls if c[1] == "/devices/command"]


@pytest.fixture
def fake_hub():
    holder: dict[str, FakeHub] = {}

    def build(hass, entry):
        hub = FakeHub(
            None, hub_id=entry.data[CONF_HUB_ID], hub_key="k", cloud_token="t",
            cloud_base=entry.data.get(CONF_CLOUD_BASE, ""), host=entry.data.get(CONF_HOST),
        )
        holder["hub"] = hub
        return hub

    with patch("custom_components.cozify_hub.build_client", side_effect=build):
        yield holder


@pytest.fixture
def entry(hass) -> MockConfigEntry:
    e = MockConfigEntry(
        domain=DOMAIN, unique_id=HUB_ID, title="Test Hub",
        data={CONF_EMAIL: "a@example.com", CONF_CLOUD_TOKEN: "t", CONF_CLOUD_BASE: "https://x/ui/0.2",
              CONF_HUB_ID: HUB_ID, CONF_HUB_KEY: "k", CONF_HOST: "192.0.2.10"},
    )
    e.add_to_hass(hass)
    return e


@pytest.fixture
async def setup(hass, entry, fake_hub):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return fake_hub["hub"]
