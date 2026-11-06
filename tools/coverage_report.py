#!/usr/bin/env python3
"""Report documented capabilities/endpoints the integration does not specially handle.

Used by the docs-sync workflow to write a useful pull request description.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "cozify_hub_dev"
spec = json.loads((PKG / "api_spec.json").read_text())

handled_caps = set(re.findall(r'"([A-Z_0-9]{3,})"', (PKG / "entity_defs.py").read_text()))
handled_caps |= set(re.findall(r'"([A-Z_0-9]{3,})"', (PKG / "switch.py").read_text()))
handled_caps |= set(re.findall(r'"([A-Z_0-9]{3,})"', (PKG / "light.py").read_text()))
handled_caps |= set(re.findall(r'"([A-Z_0-9]{3,})"', (PKG / "climate.py").read_text()))

api_src = (PKG / "api.py").read_text()
wrapped = set(re.findall(r'"(/[A-Za-z/]+)"', api_src))

print(f"Docs revision {spec['docs_revision']} ({spec['docs_date']})")
generic = sorted(c for c in spec["capabilities"] if c not in handled_caps)
print(f"\n{len(generic)} capabilities served by generic spec-driven entities only:")
print("  " + ", ".join(generic))
unwrapped = sorted(
    f"{e['method']} {e['path']}" for e in spec["endpoints"] if e["path"] not in wrapped
)
print(f"\n{len(unwrapped)} documented endpoints without a typed wrapper (reachable via HubClient.call):")
for u in unwrapped:
    print("  " + u)
sys.exit(0)
