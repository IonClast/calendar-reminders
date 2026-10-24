"""Calendar Reminders: per-event reminders with recipients for HA calendars."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from . import websocket
from .config_flow import device_subentries
from .const import (
    CONF_ALL_DAY_TIME,
    CONF_CALENDARS,
    CONF_DEFAULT_DEVICES,
    CONF_FALLBACK_DEVICE,
    CONF_LANGUAGE,
    CONF_NOTIFY_ACTION,
    CONF_SNOOZE_LONG,
    CONF_SNOOZE_SHORT,
    DEFAULT_ALL_DAY_TIME,
    DEFAULT_SNOOZE_MINUTES,
    DOMAIN,
    ENGINE_STORAGE_KEY,
    ENGINE_STORAGE_VERSION,
)
from .engine import EngineConfig, ReminderEngine
from .notifier import Device, Notifier

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SENSOR]
URL_BASE = "/calendar_reminders_static"
# Loads the Reminders section for HA's event dialog and the card.
FRONTEND_MODULE = "calendar-reminders.js"


@dataclass(slots=True)
class RuntimeData:
    """What a loaded entry runs."""

    engine: ReminderEngine
    notifier: Notifier


type CalendarRemindersConfigEntry = ConfigEntry[RuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the frontend module, register it on every page, add the WebSocket API."""
    if not hass.data.get(f"{DOMAIN}_frontend_registered"):
        www_dir = Path(__file__).parent / "www"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(www_dir), cache_headers=False)]
        )
        # The version in the URL makes browsers load a new release.
        version = (await async_get_integration(hass, DOMAIN)).version
        add_extra_js_url(hass, f"{URL_BASE}/{FRONTEND_MODULE}?v={version}")
        websocket.async_register(hass)
        hass.data[f"{DOMAIN}_frontend_registered"] = True
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: CalendarRemindersConfigEntry
) -> bool:
    """Start the engine and the notifier for this entry."""
    devices = {
        alias: Device(alias, sub.data[CONF_NOTIFY_ACTION], sub.data[CONF_LANGUAGE])
        for alias, sub in device_subentries(entry).items()
    }
    options = entry.options
    fallback = options.get(CONF_FALLBACK_DEVICE)
    config = EngineConfig(
        calendars=tuple(options.get(CONF_CALENDARS, ())),
        aliases=tuple(devices),
        # Options may still name a device whose subentry was deleted.
        default_devices=tuple(
            a for a in options.get(CONF_DEFAULT_DEVICES, ()) if a in devices
        ),
        fallback_device=fallback if fallback in devices else None,
        all_day_time=dt_util.parse_time(options.get(CONF_ALL_DAY_TIME, ""))
        or dt_util.parse_time(DEFAULT_ALL_DAY_TIME),
    )
    notifier = Notifier(
        hass,
        devices,
        fallback_device=config.fallback_device,
        snooze_minutes=(
            int(options.get(CONF_SNOOZE_SHORT, DEFAULT_SNOOZE_MINUTES[0])),
            int(options.get(CONF_SNOOZE_LONG, DEFAULT_SNOOZE_MINUTES[1])),
        ),
    )
    engine = ReminderEngine(hass, config, notifier.async_send)
    entry.async_on_unload(notifier.async_attach(engine))
    await engine.async_start()
    entry.async_on_unload(engine.async_stop)
    entry.runtime_data = RuntimeData(engine, notifier)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Options and device subentries (add, edit, delete) all land here.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CalendarRemindersConfigEntry
) -> bool:
    """Unload the sensor; async_on_unload callbacks stop the rest."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Forget fired reminders and snoozes when the integration is removed."""
    await Store(hass, ENGINE_STORAGE_VERSION, ENGINE_STORAGE_KEY).async_remove()


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """0.2.0 entries (version 1) can't be carried over: remove and add again."""
    if entry.version == 1:
        _LOGGER.error(
            "This Calendar Reminders entry is from 0.2.0 and can't be migrated. "
            "Delete it and add the integration again"
        )
        return False
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
