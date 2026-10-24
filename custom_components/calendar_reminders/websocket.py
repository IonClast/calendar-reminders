"""WebSocket API for the frontend (the dialog's Reminders section and the card)."""

from __future__ import annotations

from typing import Any

import probatio
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import slugify

from .config_flow import device_subentries
from .const import CONF_LANGUAGE, CONF_NOTIFY_ACTION, DOMAIN


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_config)


def mobile_app_devices(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Companion app registrations by their legacy notify action.

    The legacy notify platform names one action per device:
    ``mobile_app_<slugified device name>``.
    """
    return {
        f"mobile_app_{slugify(entry.data['device_name'])}": {
            "name": entry.data["device_name"],
            "user_id": entry.data.get("user_id"),
        }
        for entry in hass.config_entries.async_entries("mobile_app")
        if entry.data.get("device_name")
    }


@websocket_api.websocket_command({probatio.Required("type"): f"{DOMAIN}/config"})
@callback
def ws_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Devices (with "own" for the user asking), defaults and the all-day time."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_result(msg["id"], {"loaded": False})
        return
    entry = entries[0]
    config = entry.runtime_data.engine.config
    apps = mobile_app_devices(hass)
    devices = []
    for alias, sub in device_subentries(entry).items():
        app = apps.get(sub.data[CONF_NOTIFY_ACTION], {})
        devices.append(
            {
                "alias": alias,
                "name": app.get("name") or alias,
                "language": sub.data[CONF_LANGUAGE],
                "own": app.get("user_id") is not None
                and app.get("user_id") == connection.user.id,
            }
        )
    devices.sort(key=lambda d: d["name"].lower())
    connection.send_result(
        msg["id"],
        {
            "loaded": True,
            "devices": devices,
            "default_devices": list(config.default_devices),
            "fallback_device": config.fallback_device,
            "all_day_time": (
                config.all_day_time.strftime("%H:%M")
                if config.all_day_time
                else "00:00"
            ),
            "calendars": list(config.calendars),
        },
    )
