"""Diagnostics: configuration and engine state, without event titles."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .config_flow import device_subentries

if TYPE_CHECKING:
    from . import CalendarRemindersConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CalendarRemindersConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the entry.

    Event titles, descriptions and places are left out: the engine reports
    counts, hashed event identities and unknown #remind tokens only.
    """
    engine = entry.runtime_data.engine
    due = engine.next_due()
    return {
        "options": dict(entry.options),
        "devices": [dict(sub.data) for sub in device_subentries(entry).values()],
        "engine": {
            "config": {
                "calendars": list(engine.config.calendars),
                "aliases": list(engine.config.aliases),
                "default_devices": list(engine.config.default_devices),
                "fallback_device": engine.config.fallback_device,
                "all_day_time": (
                    engine.config.all_day_time.isoformat()
                    if engine.config.all_day_time
                    else None
                ),
            },
            "next_due": (
                {
                    "at": due[0].isoformat(),
                    "calendar": due[1].calendar,
                    "offset": due[1].offset.token(),
                    "devices": list(due[2]),
                }
                if due
                else None
            ),
            **engine.diagnostics(),
        },
    }
