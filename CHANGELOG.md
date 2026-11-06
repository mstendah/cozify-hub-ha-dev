# Changelog

## 0.2.0 - dev channel
* **Read-only mode.** A hub can now be set up (or switched in the integration options) as read-only so nothing
  can ever be written to it. It is enforced in the API client itself: every request that is not a `GET` is
  refused with `ReadOnlyError` (the one exception is the read-only `POST /rules/proposals` query), so
  services, automations and raw `send_command` calls are blocked too.
* In read-only mode the light, switch, climate and scene platforms are not loaded at all. Their state stays
  available as sensors: a **Power** binary sensor for switches/sockets/lights, a **Rule: <name>** binary
  sensor per hub rule and a **Target temperature** sensor for thermostats. Existing entries keep full control
  until the option is turned on; new setups default to read-only (shown as an extra step).
* Switching mode reloads the entry. Controllable entities of the other mode become unavailable in the entity
  registry and can be deleted there; dashboards need to point at the new sensor entities.

## 0.1.1 - dev channel
* **Separated from the production integration.** This repository is the development channel: the
  integration domain is now `cozify_hub_dev` and the folder is `custom_components/cozify_hub_dev`, so it
  can be installed next to a production `cozify_hub` without clashing (entities, services, events,
  config entries and unique ids are all namespaced separately).
* Service calls are now `cozify_hub_dev.*` (e.g. `cozify_hub_dev.deploy_custom_rule`) and the doorbell bus
  event is `cozify_hub_dev_event`.
* Display name is "Cozify Hub (dev)" in HACS and in Home Assistant's integration list.
* **Upgrading from 0.1.0:** that version used the domain `cozify_hub`. Remove the old integration entry and the
  `custom_components/cozify_hub` folder, install this version and add the integration again; entities get new ids.
* Registry clean-up for removed rules/scenes now uses the domain constant instead of a hard-coded string.
* Documentation links point to `mstendah/cozify-hub-ha-dev`.

## 0.1.0
* Initial release: local-first Cozify Hub integration with cloud login, spec-driven entities,
  hub scenes and rules, custom rule deployment, rule proposals and the workload advisor.
* Built from Cozify Hub API documentation revision 0.8.
