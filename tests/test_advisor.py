from custom_components.cozify_hub.advisor import (
    analyze_automation,
    extract_references,
    render_markdown,
    summarize,
)

HUB = {"binary_sensor.hall_motion", "light.hall", "switch.coffee", "binary_sensor.leak", "sensor.co2"}
CLASSES = {"binary_sensor.hall_motion": "motion", "binary_sensor.leak": "moisture"}
TEMPLATES = [{"type": "AUTO_LIGHT_RULE"}]


def analyze(cfg, **kw):
    return analyze_automation("automation.x", cfg, hub_entities=HUB, entity_classes=CLASSES, rule_templates=TEMPLATES, **kw)


def test_motion_light_moves_to_hub_with_template():
    cfg = {"alias": "Hall light", "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
           "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.hall"}}]}
    r = analyze(cfg)
    assert r.verdict == "move_to_hub" and r.score >= 75
    assert r.suggested_hub_template == "AUTO_LIGHT_RULE"
    assert "binary_sensor.hall_motion" in r.hub_entities


def test_notification_makes_it_split():
    cfg = {"alias": "Leak", "trigger": [{"platform": "state", "entity_id": "binary_sensor.leak", "to": "on"}],
           "action": [{"service": "light.turn_on", "entity_id": "light.hall"},
                      {"service": "notify.mobile_app_phone", "data": {"message": "Leak"}}]}
    r = analyze(cfg)
    assert r.verdict == "split"
    assert any("Safety" in x for x in r.reasons)


def test_ha_context_stays_in_ha():
    cfg = {"alias": "Away", "triggers": [{"trigger": "zone", "entity_id": "device_tracker.phone", "zone": "zone.home", "event": "leave"}],
           "actions": [{"action": "switch.turn_off", "target": {"entity_id": "switch.coffee"}}]}
    r = analyze(cfg)
    assert r.verdict == "keep_in_ha"
    assert any("zone" in x for x in r.reasons)


def test_templates_and_flow_control_reduce_score():
    cfg = {"alias": "Complex", "triggers": [{"trigger": "state", "entity_id": "sensor.co2"}],
           "actions": [{"choose": [{"conditions": [{"condition": "template", "value_template": "{{ states('sensor.co2')|int > 900 and is_state('light.hall','off') }}"}],
                                    "sequence": [{"action": "light.turn_on", "entity_id": "light.hall"}]}]}]}
    refs = extract_references(cfg)
    assert {"sensor.co2", "light.hall"} <= refs["entities"] and refs["templates"] and "choose" in refs["complex"]
    assert analyze(cfg).score < analyze({**cfg, "actions": [{"action": "light.turn_on", "entity_id": "light.hall"}]}).score


def test_unrelated_automation_ignored():
    cfg = {"alias": "Other", "triggers": [{"trigger": "state", "entity_id": "light.kitchen"}], "actions": []}
    assert analyze(cfg).verdict == "not_related"


def test_cloud_connection_raises_score():
    cfg = {"alias": "Hall light", "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion"}],
           "actions": [{"action": "light.turn_on", "entity_id": "light.hall"}, {"action": "media_player.play_media"}]}
    assert analyze(cfg, connection="cloud").score > analyze(cfg, connection="local").score


def test_markdown_and_summary():
    recs = [analyze({"alias": "A", "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion"}],
                     "actions": [{"action": "light.turn_on", "entity_id": "light.hall"}]})]
    assert summarize(recs)["move_to_hub"] == 1
    md = render_markdown(recs)
    assert "Move to the hub" in md and "**A**" in md
