"""Access to the generated API specification (``api_spec.json``)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SPEC_FILE = Path(__file__).with_name("api_spec.json")


@lru_cache(maxsize=1)
def load_spec() -> dict[str, Any]:
    """Load the spec; an empty skeleton keeps the integration alive if missing."""
    try:
        return json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"docs_revision": None, "capabilities": {}, "endpoints": [], "feature_codes": {}}


def docs_revision() -> str | None:
    return load_spec().get("docs_revision")


def capability_attributes(capability: str) -> list[dict[str, Any]]:
    """Attributes the docs define for a capability."""
    return load_spec().get("capabilities", {}).get(capability, {}).get("attributes", [])


def is_known_capability(capability: str) -> bool:
    return capability in load_spec().get("capabilities", {})


def feature_name(code: int | str) -> str | None:
    return load_spec().get("feature_codes", {}).get(str(code))


def state_key(path: str) -> str | None:
    """'state.isOn' -> 'isOn'. Attributes outside ``state`` return None."""
    if path.startswith("state."):
        return path[len("state.") :]
    return None
