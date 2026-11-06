"""Custom rule deployment helpers.

Installing a rule template with a type that already exists *deletes its
instances* on the hub and resets in-memory state. ``deploy_custom_rule``
therefore snapshots the instances first and recreates them afterwards.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .api import CozifyError, HubClient

FEATURE_CUSTOM_RULES = 2
MAX_SOURCE_BYTES = 200_000
_TYPE_RE = re.compile(r"^\s*type\s*=\s*['\"]([A-Za-z0-9_]+)['\"]", re.M)


class RuleError(CozifyError):
    """Invalid rule deployment request."""


def extract_rule_type(source: str) -> str | None:
    """Return the ``type = '...'`` of the rule class in the source."""
    m = _TYPE_RE.search(source)
    return m.group(1) if m else None


def validate_source(source: str) -> str:
    """Cheap sanity checks; the hub does the real validation. Returns the rule type."""
    if len(source.encode()) > MAX_SOURCE_BYTES:
        raise RuleError("rule source too large")
    if "class " not in source or "(Rule)" not in source:
        raise RuleError("source must define a class deriving from Rule")
    rule_type = extract_rule_type(source)
    if not rule_type:
        raise RuleError("rule class needs a type = '...' attribute")
    return rule_type


def snapshot_instances(rules: dict[str, Any], rule_type: str) -> list[dict[str, Any]]:
    snaps = []
    for rule in rules.values():
        cfg = rule.get("config") or {}
        if cfg.get("configType") != rule_type:
            continue
        new_cfg = copy.deepcopy(cfg)
        new_cfg["id"] = None
        snaps.append(
            {
                "old_id": rule.get("id"),
                "config": new_cfg,
                "was_on": bool(rule.get("is_on")),
                "timers": copy.deepcopy(rule.get("timers") or []),
            }
        )
    return snaps


async def deploy_custom_rule(
    client: HubClient,
    source: str,
    *,
    preserve_instances: bool = True,
    turn_on: bool = True,
    new_instance_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Install/upgrade a custom rule and recreate its instances."""
    rule_type = validate_source(source)
    if client.features and FEATURE_CUSTOM_RULES not in client.features:
        raise RuleError("this hub does not have the CUSTOM_RULES feature")

    before = await client.rules()
    snaps = snapshot_instances(before, rule_type) if preserve_instances else []
    await client.install_rule_template(source)

    created: list[str] = []
    known = set((await client.rules()).keys())
    for snap in snaps:
        on_cfg = {"type": "RULE_ON_CFG", "scenes": [], "timers": snap["timers"]}
        await client.save_rule(snap["config"], on_cfg)
        now = await client.rules()
        new_ids = [r for r in now if r not in known and (now[r].get("config") or {}).get("configType") == rule_type]
        for rid in new_ids:
            known.add(rid)
            created.append(rid)
            await client.rule_command(rid, snap["was_on"] and turn_on)

    if new_instance_config is not None:
        cfg = {"type": "CONFIG", "id": None, "configType": rule_type, **new_instance_config}
        await client.save_rule(cfg)
        now = await client.rules()
        for rid, r in now.items():
            if rid not in known and (r.get("config") or {}).get("configType") == rule_type:
                created.append(rid)
                if turn_on:
                    await client.rule_command(rid, True)

    return {
        "rule_type": rule_type,
        "instances_before": len(snaps),
        "instances_recreated": len(created),
        "rule_ids": created,
    }
