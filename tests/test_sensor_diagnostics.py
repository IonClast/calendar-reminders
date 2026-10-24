"""sensor.calendar_reminders_next and the config entry diagnostics."""

import json
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.calendar_reminders.const import DOMAIN
from custom_components.calendar_reminders.notifier import action_id

from .common import CAL, add_event, advance, oslo
from .test_setup import setup, standard_entry

SENSOR = "sensor.calendar_reminders_next"


async def test_sensor_follows_the_engine(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    async_mock_service(hass, "notify", "mobile_app_annas_phone")
    async_mock_service(hass, "notify", "mobile_app_bens_phone")
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h !"
    )
    entry = standard_entry(hass)
    await setup(hass, entry)

    state = hass.states.get(SENSOR)
    assert state is not None
    assert state.state == "2026-11-02T08:00:00+00:00"  # 09:00 in Oslo (CET)
    assert state.attributes["device_class"] == "timestamp"
    assert state.attributes["friendly_name"] == "Calendar Reminders Next reminder"
    assert state.attributes["summary"] == "Dentist"
    assert state.attributes["calendar"] == CAL
    assert state.attributes["start"] == "2026-11-02T10:00:00+01:00"
    assert state.attributes["offset"] == "1h"
    assert state.attributes["devices"] == ["anna", "ben"]
    assert state.attributes["important"] is True
    assert state.attributes["snoozed"] is False
    assert state.attributes["pending"] == 1

    # A second event, saved later and sooner, takes over at once (push).
    await add_event(
        hass, freezer, calendar, "Call", oslo(2026, 11, 2, 9, 0), "#remind 15m @ben"
    )
    state = hass.states.get(SENSOR)
    assert state.state == "2026-11-02T07:45:00+00:00"
    assert state.attributes["devices"] == ["ben"]
    assert state.attributes["pending"] == 2

    await advance(hass, freezer, oslo(2026, 11, 2, 8, 45))
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    assert hass.states.get(SENSOR).state == STATE_UNKNOWN
    assert hass.states.get(SENSOR).attributes == {
        "pending": 0,
        "device_class": "timestamp",
        "friendly_name": "Calendar Reminders Next reminder",
    }

    # Snooze on Ben's phone: the sensor shows the snooze, for Ben only.
    key = next(
        k
        for k, r in entry.runtime_data.engine.reminders.items()
        if r.summary == "Dentist"
    )
    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": action_id("SNOOZE10", key, "ben")}
    )
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.state == "2026-11-02T08:10:00+00:00"
    assert state.attributes["devices"] == ["ben"]
    assert state.attributes["snoozed"] is True

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == STATE_UNAVAILABLE


async def test_sensor_registry_entries(hass: HomeAssistant, calendar: Any) -> None:
    entry = standard_entry(hass)
    await setup(hass, entry)
    entity = er.async_get(hass).async_get(SENSOR)
    assert entity is not None
    assert entity.unique_id == f"{entry.entry_id}_next"
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device is not None
    assert device.name == "Calendar Reminders"
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.identifiers == {(DOMAIN, entry.entry_id)}


async def test_diagnostics_have_no_titles(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    calendar: Any,
    # After `calendar`, so its access token is issued at the frozen time.
    hass_client: ClientSessionGenerator,
) -> None:
    await add_event(
        hass,
        freezer,
        calendar,
        "Secret dentist",
        oslo(2026, 11, 2, 10, 0),
        "Bring the papers\n#remind 1h @bob",
        location="Main Street Clinic",
    )
    entry = standard_entry(hass)
    await setup(hass, entry)
    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    text = json.dumps(diag)
    for private in ("Secret", "dentist", "papers", "Main Street"):
        assert private not in text
    assert diag["options"]["fallback_device"] == "anna"
    assert {d["alias"] for d in diag["devices"]} == {"anna", "ben"}
    engine = diag["engine"]
    assert engine["config"] == {
        "calendars": [CAL],
        "aliases": ["anna", "ben"],
        "default_devices": ["anna", "ben"],
        "fallback_device": "anna",
        "all_day_time": "18:00:00",
    }
    assert engine["next_due"] == {
        "at": "2026-11-02T08:00:00+00:00",
        "calendar": CAL,
        "offset": "1h",
        "devices": ["anna"],
    }
    assert engine["calendars"][CAL] == {
        "events": 1,
        "subscribed": True,
        "unavailable": False,
    }
    assert engine["unknown_tokens"][0]["tokens"] == ["@bob"]
    assert engine["pending"] == 1


async def test_diagnostics_without_upcoming(
    hass: HomeAssistant, calendar: Any, hass_client: ClientSessionGenerator
) -> None:
    entry = standard_entry(hass)
    await setup(hass, entry)
    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert diag["engine"]["next_due"] is None
    assert diag["engine"]["reminders"] == 0
