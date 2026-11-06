"""Constants for the Cozify Hub integration."""

from __future__ import annotations

DOMAIN = "cozify_hub"
MANUFACTURER = "Cozify"

CONF_EMAIL = "email"
CONF_CLOUD_TOKEN = "cloud_token"
CONF_CLOUD_BASE = "cloud_base"
CONF_HUB_ID = "hub_id"
CONF_HUB_KEY = "hub_key"
CONF_HUB_NAME = "hub_name"
CONF_HOST = "host"
CONF_CLIENT_ID = "client_id"

# Options
CONF_PREFER_LOCAL = "prefer_local"

# Cloud endpoints. Hubs running 1.14.9.* use api.cozify.fi, 1.14.15+ use
# cloudapi.cozify.io. Both expose identical paths.
CLOUD_BASES = (
    "https://api.cozify.fi/ui/0.2",
    "https://cloudapi.cozify.io/ui/0.2",
)
LOCAL_PORT = 8893

# Documentation recommends ~2 s between polls on LAN and ~5 s through the cloud.
POLL_INTERVAL_LOCAL = 2
POLL_INTERVAL_REMOTE = 5

# Cloud tokens live 4 weeks; refresh when less than 2 weeks remain.
TOKEN_REFRESH_MARGIN_S = 14 * 24 * 3600

EVENT_DOORBELL = "cozify_hub_event"
SIGNAL_NEW_DEVICES = f"{DOMAIN}_new_devices_{{}}"

# Services
SERVICE_RUN_SCENE = "run_scene"
SERVICE_SET_RULE_STATE = "set_rule_state"
SERVICE_DELETE_RULE = "delete_rule"
SERVICE_DEPLOY_CUSTOM_RULE = "deploy_custom_rule"
SERVICE_GET_RULE_LOG = "get_rule_log"
SERVICE_GET_RULE_PROPOSALS = "get_rule_proposals"
SERVICE_CREATE_RULE_FROM_PROPOSAL = "create_rule_from_proposal"
SERVICE_SUGGEST_WORKLOAD_SPLIT = "suggest_workload_split"
SERVICE_SEND_COMMAND = "send_command"
