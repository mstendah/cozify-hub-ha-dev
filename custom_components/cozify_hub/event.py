"""Event entities for alert style devices (doorbells ...)."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CozifyCoordinator
from .entity import CozifyEntity, setup_device_platform


class CozifyAlertEvent(CozifyEntity, EventEntity):
    _attr_name = "Alert"
    _attr_event_types = ["pressed"]

    def __init__(self, coordinator: CozifyCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "alert_event")
        model = (coordinator.devices[device_id].get("type") or "").upper()
        if model == "DOORBELL":
            self._attr_device_class = EventDeviceClass.DOORBELL
            self._attr_name = "Doorbell"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_alert_{self.coordinator.client.hub_id}_{self.device_id}",
                self._fire,
            )
        )

    @callback
    def _fire(self, marker: int) -> None:
        self._trigger_event("pressed", {"timestamp": marker})
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_device_platform(
        hass, entry, async_add_entities,
        lambda c, dev_id: [CozifyAlertEvent(c, dev_id)]
        if "GENERATE_ALERT" in c.capabilities(dev_id) and "SMOKE" not in c.capabilities(dev_id)
        else [],
    )
