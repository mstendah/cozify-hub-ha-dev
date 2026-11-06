"""Hub scenes as Home Assistant scenes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CozifyCoordinator
from .entity import CozifyHubEntity


class CozifyScene(CozifyHubEntity, Scene):
    def __init__(self, coordinator: CozifyCoordinator, scene_id: str) -> None:
        super().__init__(coordinator, f"scene_{scene_id}")
        self.scene_id = scene_id

    @property
    def name(self) -> str:  # type: ignore[override]
        return (self.coordinator.scenes.get(self.scene_id) or {}).get("name") or self.scene_id

    @property
    def available(self) -> bool:
        return super().available and self.scene_id in self.coordinator.scenes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        sc = self.coordinator.scenes.get(self.scene_id) or {}
        return {"scene_id": self.scene_id, "is_on": sc.get("isOn"), "category": sc.get("category")}

    async def async_activate(self, **kwargs: Any) -> None:
        await self.coordinator.client.scene_command(self.scene_id, True)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: CozifyCoordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new = [s for s in coordinator.scenes if s not in known]
        if new:
            known.update(new)
            async_add_entities([CozifyScene(coordinator, s) for s in new])
        gone = known - set(coordinator.scenes)
        if gone and coordinator.last_update_success:
            registry = er.async_get(hass)
            for scene_id in gone:
                ent = registry.async_get_entity_id(
                    "scene", DOMAIN, f"{coordinator.client.hub_id}_scene_{scene_id}"
                )
                if ent:
                    registry.async_remove(ent)
                known.discard(scene_id)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))
