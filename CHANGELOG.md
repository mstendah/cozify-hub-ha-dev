# Changelog

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
