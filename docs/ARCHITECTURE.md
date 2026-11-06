# Architecture

```
Cozify cloud  <-- login (email OTP), hub keys, LAN lookup, relay
      |
 HubClient  ------ local:  http://<hub>:8893/cc/<api>/...   (Authorization: HubKey)
      |      \---- relay:  <cloud>/hub/remote/cc/<api>/...   (Authorization: cloud token, X-Hub-Key)
      |
CozifyCoordinator  poll deltas (/hub/poll?ts=) -> mirrors devices/rooms/groups/scenes/rules
      |
 platforms (light, switch, sensor, binary_sensor, climate, event, scene) + services + advisor
      ^
 api_spec.json  <-- tools/sync_api_docs.py <-- published Hub API docs
```

## Design rules

1. **Spec driven.** `api_spec.json` lists every capability, its state attributes (type, unit, writable),
   documented endpoints, command types and feature codes. Platforms ask the spec what a device can report;
   `entity_defs.py` only adds presentation (device class, unit) for the ones we understand.
   Anything documented but not curated becomes a disabled diagnostic entity.
2. **Guards, not guesses.** Tests assert curated attributes still exist in the docs, the client only calls documented
   endpoints and only sends documented command types. A docs change that breaks an assumption fails CI in the sync PR.
3. **Local first, cloud fallback.** One client, two transports. A failed LAN call pauses local use for 60 s.
4. **Single-use login codes.** The config flow never repeats a login; later entries on the same account reuse the token.
5. **No silent edits.** The advisor only reports. Rule deployment recreates instances explicitly because the hub deletes
   them when a template is reinstalled.

## Adding support for a new capability

1. Run `python tools/sync_api_docs.py` and `python tools/coverage_report.py`.
2. Generic entities already exist. To polish: add the capability to `CURATED_SENSORS`/`CURATED_BINARY` and `CURATED_ATTRS`
   in `entity_defs.py`.
3. For controllable devices add a platform following `climate.py` and register it in `__init__.PLATFORMS`.
4. Add a fixture to `tests/fixtures/devices.json` (anonymised) and a test.
