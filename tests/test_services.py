import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.cozify_hub.const import DOMAIN
from custom_components.cozify_hub.rules import RuleError, extract_rule_type, validate_source

from .conftest import RULE

SRC = "from cozify import Rule\nclass Coffee(Rule):\n    type = 'COFFEE_WATCH'\n    name = 'x'\n"


def test_rule_source_validation():
    assert extract_rule_type(SRC) == "COFFEE_WATCH"
    assert validate_source(SRC) == "COFFEE_WATCH"
    with pytest.raises(RuleError):
        validate_source("print('hi')")
    with pytest.raises(RuleError):
        validate_source("class A(Rule):\n    pass\n")


async def test_deploy_preserves_instances(hass, setup):
    """Reinstalling a template wipes instances on the real hub; we must recreate them."""
    setup.rules_data[RULE]["timers"] = [{"type": "RULETIME"}]
    res = await hass.services.async_call(
        DOMAIN, "deploy_custom_rule", {"source": SRC}, blocking=True, return_response=True
    )
    assert res["rule_type"] == "COFFEE_WATCH"
    assert res["instances_before"] == 1 and res["instances_recreated"] == 1
    new_id = res["rule_ids"][0]
    assert new_id != RULE and RULE not in setup.rules_data
    new_rule = setup.rules_data[new_id]
    assert new_rule["config"]["name"] == "Coffee watcher"
    assert new_rule["timers"] == [{"type": "RULETIME"}]
    assert new_rule["is_on"] is True
    # the old id was snapshotted, install happened between read and recreate
    order = [c[0] + " " + c[1] for c in setup.calls if c[1].startswith("/rules")]
    assert order.index("POST /rules/template") < order.index("PUT /rules")


async def test_deploy_requires_custom_rules_feature(hass, setup):
    setup.features = [5]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "deploy_custom_rule", {"source": SRC}, blocking=True)


async def test_rule_and_scene_services(hass, setup):
    await hass.services.async_call(DOMAIN, "set_rule_state", {"rule": "coffee watcher", "state": "off"}, blocking=True)
    assert setup.rules_data[RULE]["is_on"] is False
    await hass.services.async_call(DOMAIN, "run_scene", {"scene": "Evening", "state": "off"}, blocking=True)
    assert setup.calls[-1][2] == [{"type": "CMD_SCENE_OFF", "id": "30000000-0000-4000-8000-000000000001"}]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "run_scene", {"scene": "Nope"}, blocking=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "delete_rule", {"rule": "Coffee watcher", "confirm": False}, blocking=True)
    await hass.services.async_call(DOMAIN, "delete_rule", {"rule": "Coffee watcher", "confirm": True}, blocking=True)
    assert RULE not in setup.rules_data


async def test_rule_log_and_proposals(hass, setup):
    log = await hass.services.async_call(DOMAIN, "get_rule_log", {}, blocking=True, return_response=True)
    assert "hello" in log["log"]
    setup.proposals = [{"type": "RULE_PROPOSAL", "config": {"configType": "AUTO_LIGHT_RULE", "name": "Hall"}}]
    from .conftest import LIGHT
    res = await hass.services.async_call(DOMAIN, "get_rule_proposals", {"device_ids": [LIGHT]}, blocking=True, return_response=True)
    assert res["proposals"][0]["config"]["configType"] == "AUTO_LIGHT_RULE"
    await hass.services.async_call(DOMAIN, "create_rule_from_proposal",
                                   {"proposal": res["proposals"][0], "name": "Mine"}, blocking=True)
    assert any(r["config"]["name"] == "Mine" for r in setup.rules_data.values())


async def test_proposals_from_entity_ids(hass, setup):
    from homeassistant.helpers import entity_registry as er

    from .conftest import LIGHT
    reg = er.async_get(hass)
    ent = next(e for e in reg.entities.values() if e.unique_id.endswith(f"{LIGHT}_light"))
    await hass.services.async_call(DOMAIN, "get_rule_proposals", {"entity_ids": [ent.entity_id]}, blocking=True, return_response=True)
    body = [c for c in setup.calls if c[1] == "/rules/proposals"][-1][2][0]
    assert body["deviceIds"] == [LIGHT] and body["type"] == "CMD_GET_PROPOSALS"


async def test_raw_command(hass, setup):
    await hass.services.async_call(DOMAIN, "send_command", {"commands": [{"type": "CMD_DEVICE_ON", "id": "x"}]}, blocking=True)
    assert setup.commands()[-1] == [{"type": "CMD_DEVICE_ON", "id": "x"}]


async def test_suggest_workload_split_service(hass, setup):
    res = await hass.services.async_call(DOMAIN, "suggest_workload_split", {}, blocking=True, return_response=True)
    assert res["summary"]["total"] == 0 and "Cozify Hub workload" in res["markdown"]
