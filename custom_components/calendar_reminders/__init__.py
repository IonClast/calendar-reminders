"""Calendar Reminders — native-feeling reminders for HA calendar events."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .manager import ReminderManager

URL_BASE = "/calendar_reminders_static"
CARD_FILENAME = "calendar-reminder-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled dashboard card and auto-register it."""
    if not hass.data.get(f"{DOMAIN}_frontend_registered"):
        www_dir = Path(__file__).parent / "www"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(www_dir), cache_headers=False)]
        )
        add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILENAME}")
        hass.data[f"{DOMAIN}_frontend_registered"] = True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Calendar Reminders from a config entry."""
    manager = ReminderManager(hass, entry)
    await manager.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    manager: ReminderManager | None = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id, None
    )
    if manager:
        await manager.async_stop()
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
