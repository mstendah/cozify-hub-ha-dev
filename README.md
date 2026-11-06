# Cozify Hub for Home Assistant

A [HACS](https://hacs.xyz) custom integration for [Cozify](https://cozify.fi) hubs. It talks to the
documented Cozify Hub API, prefers your **local network** and falls back to the **Cozify cloud relay**.

What makes it different from a plain device bridge:

* **Hub assets are first-class HA citizens.** Devices, sensors, lights, thermostats, power meters,
  doorbells, hub **scenes** and hub **rules** (as switches) are all normal entities you can use in
  automations, dashboards and voice assistants.
* **Custom rules.** Deploy, upgrade and inspect the Python custom rules that run *on the hub*
  (`cozify_hub.deploy_custom_rule`, `get_rule_log`) - without losing the rule instances and their settings.
* **Workload advisor.** `cozify_hub.suggest_workload_split` reads your HA automations and tells you which
  should run on the hub (works offline, no round trip), which should be split, and which belong in Home Assistant.
* **Hub rule proposals.** Ask the hub which rules it recommends for a device and create them from HA.
* **Evolves with the API documentation.** Entities are generated from a spec that is *generated from the
  official API docs* (`tools/sync_api_docs.py`), a weekly workflow opens a PR when the docs change, and
  tests fail if the docs rename something this integration relies on.

## Installation

1. HACS -> Integrations -> three dots -> **Custom repositories** -> add
   `https://github.com/mstendah/cozify-hub-ha-dev` as category *Integration*.
2. Install **Cozify Hub**, restart Home Assistant.
3. Settings -> Devices & services -> **Add integration** -> *Cozify Hub*.
4. Enter your Cozify account email. Cozify sends a **one-time code** to that address; enter it.
   (The code is single use. If it fails, request a new one.)
5. Pick the hub. The integration looks for the hub on your LAN (port 8893) and stores the address;
   otherwise it uses the cloud relay. You can set/override the address under *Configure*.

Several hubs on one account: add the integration again - the existing login is reused, no new code needed.

> Cloud relay access needs the remote-access feature on the hub (HTTP 402 otherwise). Local access does not.

## Entities

| Cozify capability | Home Assistant |
| --- | --- |
| `CONTROL_LIGHT` (+ `COLOR_HS`, `COLOR_TEMP`, `BRIGHTNESS`, `TRANSITION`) | `light` |
| `ON_OFF` (sockets, relays) | `switch` |
| `CONTROL_TEMPERATURE` | `climate` (heat, target temperature) |
| `TEMPERATURE`, `HUMIDITY`, `CO2`, `PRESSURE`, `LUX`, power/energy/current/phase values, battery | `sensor` |
| `MOTION`, `CONTACT`, `MOISTURE`, `SMOKE`, `TWILIGHT`, `SIREN`, battery low, reachable | `binary_sensor` |
| `GENERATE_ALERT` (doorbells) | `event` + bus event `cozify_hub_event` |
| Hub scenes | `scene` |
| Hub rules | `switch` ("Rule: ...") |
| Everything else the docs define | disabled, diagnostic generic `sensor`/`binary_sensor` (enable what you need) |

Not yet supported (shown in diagnostics): aircon, shutters/covers, cameras, speakers/media. They need
verified command semantics; use `cozify_hub.send_command` for raw access meanwhile.

### Doorbell example

```yaml
automation:
  - alias: Blink the hall light when someone rings
    triggers:
      - trigger: state
        entity_id: event.front_door_doorbell
    actions:
      - action: light.turn_on
        target: {entity_id: light.hall}
        data: {hs_color: [120, 100], transition: 0}
```

## Services

| Service | Purpose |
| --- | --- |
| `cozify_hub.run_scene` | Turn a hub scene on/off by name or id |
| `cozify_hub.set_rule_state` | Enable/disable a hub rule |
| `cozify_hub.delete_rule` | Delete a rule instance (`confirm: true`) |
| `cozify_hub.deploy_custom_rule` | Install/upgrade a Python custom rule, preserving instances and their settings |
| `cozify_hub.get_rule_log` | Read the rule log (response data; times are UTC) |
| `cozify_hub.get_rule_proposals` | Ask the hub for rule proposals for entities/devices |
| `cozify_hub.create_rule_from_proposal` | Create a rule from a proposal |
| `cozify_hub.suggest_workload_split` | Hub vs HA recommendations for your automations |
| `cozify_hub.send_command` | Raw `PUT /devices/command` payloads for anything not modelled yet |

### Deploying a custom rule

```yaml
action: cozify_hub.deploy_custom_rule
data:
  file: /config/cozify/my_rule.py     # must be in allowlist_external_dirs; or pass `source:`
  preserve_instances: true
```

Reinstalling a template with an existing type **deletes its instances on the hub** and resets their state.
The service snapshots the instances first, installs the template, recreates them with the same inputs,
outputs, extras and timers, and restores their on/off state. Needs the hub's `CUSTOM_RULES` feature.

### Workload advisor

```yaml
action: cozify_hub.suggest_workload_split
data: {notify: true}
response_variable: advice
```

Each automation that touches Cozify entities gets a **hub fit score (0-100)** and a verdict:

* `move_to_hub` - only Cozify devices, no HA-only services or templates; a hub rule runs it without HA.
* `split` - trigger/device part on the hub, notification/integration part in HA.
* `keep_in_ha` - depends on presence, zones, templates, other integrations.

Safety-related sensors (smoke, moisture, ...) and cloud-only connections raise the score. It only
*suggests* - it never edits automations or rules.

## Connection model

* Local: `GET http://<hub>:8893/cc/<api>/hub/poll` every 2 s with the HubKey.
* Cloud: relay with your cloud token + HubKey every 5 s, as the API docs recommend.
* The API version prefix is derived from the hub software version; `410 Gone` triggers a re-bootstrap.
* The cloud token is refreshed automatically before it expires; if it cannot be, Home Assistant asks you to sign in again.
* Poll deltas are merged into a local mirror (devices, rooms, groups, scenes, rules).

## Keeping up with the API documentation

```
tools/sync_api_docs.py   docs -> custom_components/cozify_hub/api_spec.json
tools/coverage_report.py what the integration only handles generically
.github/workflows/api-docs-sync.yml   weekly: sync, test, open a PR
tests/test_sync_tool.py  guards: curated attributes still documented, client uses documented endpoints
```

When Cozify publishes a new documentation revision the workflow regenerates the spec and opens a PR.
New capabilities immediately show up as generic diagnostic entities; curate them in
`entity_defs.py` when you know what they mean. The *API documentation revision* diagnostic sensor
shows which revision a running install was built from.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
python tools/sync_api_docs.py --check
```

## Known limitations

* Colour-temperature lights use `colorMode: "ct"`; the docs only spell out `"hs"` so this is unverified.
* Rule/scene entities appear and disappear as the hub reports them; rule logs are limited by the hub's buffer.
* Zeroconf discovery is not implemented (the API docs list it as an option); LAN lookup uses the cloud
  `lan_ip` endpoint and you can set the address manually.

## Disclaimer

Unofficial community integration, not affiliated with Cozify Oy. Built from the public Cozify Hub API documentation.

## License

MIT
