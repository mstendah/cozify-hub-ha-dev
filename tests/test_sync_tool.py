"""The docs->spec generator and the guards that keep the integration in step with the docs."""
import importlib.util
import sys
from pathlib import Path

from custom_components.cozify_hub import spec
from custom_components.cozify_hub.entity_defs import CURATED_ATTRS

ROOT = Path(__file__).resolve().parent.parent
spec_mod = importlib.util.spec_from_file_location("sync_api_docs", ROOT / "tools" / "sync_api_docs.py")
sync = importlib.util.module_from_spec(spec_mod)
sys.modules["sync_api_docs"] = sync
spec_mod.loader.exec_module(sync)  # type: ignore[union-attr]


def test_parse_mini_docs():
    s = sync.build_spec((ROOT / "tests/fixtures/mini_api.md").read_text(), "mini")
    assert s["docs_revision"] == "0.9" and s["docs_date"] == "2026-10-01"
    assert s["changelog"][0]["summary"].startswith("Documented")
    assert s["feature_codes"] == {"2": "CUSTOM_RULES", "20": "SPOT_PRICES"}
    caps = s["capabilities"]
    assert caps["ON_OFF"]["attributes"][0] == {"description": "", "path": "state.isOn", "type": "boolean", "writable": True}
    ct = caps["CONTROL_TEMPERATURE"]["attributes"]
    assert ct[0]["writable"] is True and ct[0]["unit"] == "Celsius"
    assert ct[1]["writable"] is False and ct[1]["range"] == "0.0, 1.0"
    assert caps["SHUTTER"]["attributes"][0]["values"] == {"-1": "Motor down", "0": "Stopped"}
    assert caps["NEW_CAP"]["attributes"][0]["unit"] == "Percent"
    assert {(e["method"], e["path"]) for e in s["endpoints"]} == {("GET", "/devices"), ("PUT", "/devices/command")}
    assert s["command_types"] == ["CMD_DEVICE_ON"]


def test_check_mode_detects_stale_spec(tmp_path, monkeypatch):
    out = tmp_path / "spec.json"
    monkeypatch.setattr(sys, "argv", ["x", "--source", str(ROOT / "tests/fixtures/mini_api.md"), "--out", str(out)])
    assert sync.main() == 0 and out.exists()
    monkeypatch.setattr(sys, "argv", ["x", "--source", str(ROOT / "tests/fixtures/mini_api.md"), "--out", str(out), "--check"])
    assert sync.main() == 0
    out.write_text("{}")
    assert sync.main() == 1


def test_shipped_spec_is_populated():
    s = spec.load_spec()
    assert s["docs_revision"] and len(s["capabilities"]) > 50 and len(s["endpoints"]) > 50 and s["feature_codes"]
    assert "2" in s["feature_codes"]  # CUSTOM_RULES


def test_curated_mappings_still_exist_in_docs():
    """If the docs rename or drop an attribute we curated, fail loudly so a human looks."""
    missing = []
    for cap, attrs in CURATED_ATTRS.items():
        if not spec.is_known_capability(cap):
            missing.append(f"capability {cap}")
            continue
        documented = {spec.state_key(a["path"]) for a in spec.capability_attributes(cap)}
        for attr in attrs:
            if attr not in documented:
                missing.append(f"{cap}.{attr}")
    # Known gaps in the docs themselves (documented elsewhere in the text).
    allowed = {"DEVICE.reachable", "GENERATE_ALERT.alert"} - {"DEVICE.reachable"}
    assert not [m for m in missing if m not in allowed], missing


def test_client_only_uses_documented_endpoints():
    """Every endpoint the typed client wraps must exist in the docs."""
    import re

    src = (ROOT / "custom_components/cozify_hub/api.py").read_text()
    used = set(re.findall(r'call\(\s*"(GET|PUT|POST|DELETE)",\s*"(/[A-Za-z/]+)"', src))
    used |= set(re.findall(r'call\(\s*"(GET|PUT|POST|DELETE)",\s*\n?\s*"(/[A-Za-z/]+)"', src))
    documented = {(e["method"], e["path"]) for e in spec.load_spec()["endpoints"]}
    assert used, "no endpoint calls found - regex out of date"
    assert not used - documented, f"undocumented endpoints used: {used - documented}"


def test_commands_we_send_are_documented():
    import re

    sent = set()
    for f in (ROOT / "custom_components/cozify_hub").glob("*.py"):
        sent |= set(re.findall(r'"(CMD_[A-Z_]+)"', f.read_text()))
    documented = set(spec.load_spec()["command_types"])
    # CMD_DEVICE_OFF/ON and friends appear in the docs examples; STATE_* are not commands.
    assert not sent - documented, f"commands not found in docs: {sent - documented}"
