"""The Cozify Hub integration."""

from __future__ import annotations

import logging
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import HubClient
from .const import (
    CLOUD_BASES,
    CONF_CLIENT_ID,
    CONF_CLOUD_BASE,
    CONF_CLOUD_TOKEN,
    CONF_HOST,
    CONF_HUB_ID,
    CONF_HUB_KEY,
    CONF_PREFER_LOCAL,
    DOMAIN,  # noqa: F401
)
from .coordinator import CozifyCoordinator
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.EVENT,
    Platform.LIGHT,
    Platform.SCENE,
    Platform.SENSOR,
    Platform.SWITCH,
]

type CozifyConfigEntry = ConfigEntry[CozifyCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_services(hass)
    return True


def build_client(hass: HomeAssistant, entry: ConfigEntry) -> HubClient:
    data = entry.data
    return HubClient(
        async_get_clientsession(hass),
        hub_id=data[CONF_HUB_ID],
        hub_key=data[CONF_HUB_KEY],
        cloud_token=data.get(CONF_CLOUD_TOKEN),
        cloud_base=data.get(CONF_CLOUD_BASE, CLOUD_BASES[0]),
        host=entry.options.get(CONF_HOST) or data.get(CONF_HOST),
        prefer_local=entry.options.get(CONF_PREFER_LOCAL, True),
        client_id=data.get(CONF_CLIENT_ID) or f"ha-{uuid.uuid4()}",
    )


async def async_setup_entry(hass: HomeAssistant, entry: CozifyConfigEntry) -> bool:
    client = build_client(hass, entry)
    coordinator = CozifyCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Register the hub device so child devices can reference it.
    from homeassistant.helpers import device_registry as dr

    from .entity import hub_device_info

    dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, **hub_device_info(coordinator))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: CozifyConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CozifyConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
