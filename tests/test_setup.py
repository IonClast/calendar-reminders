"""Setup tests: the integration loaded from a config entry, end to end."""

from datetime import date, time
from typing import Any
from unittest.mock import MagicMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.calendar_reminders.const import DOMAIN, ENGINE_STORAGE_KEY

from .common import CAL, add_event, advance, oslo
from .test_config_flow import device, make_entry


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def standard_entry(hass: HomeAssistant, **options: Any) -> MockConfigEntry:
    return make_entry(
        hass,
        device("anna", "mobile_app_annas_phone", "en"),
        device("ben", "mobile_app_bens_phone", "nb"),
        **{"default_devices": ["anna", "ben"], "fallback_device": "anna", **options},
    )


async def test_reminder_end_to_end(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    calendar: Any,
    frontend_stub: MagicMock,
) -> None:
    anna = async_mock_service(hass, "notify", "mobile_app_annas_phone")
    ben = async_mock_service(hass, "notify", "mobile_app_bens_phone")
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h"
    )
    entry = standard_entry(hass)
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    frontend_stub.assert_called_once_with(
        hass, "/calendar_reminders_static/calendar-reminders.js?v=0.4.0"
    )

    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    assert [c.data["title"] for c in anna] == ["⏰ In 1 hour: Dentist"]
    assert [c.data["title"] for c in ben] == ["⏰ Om 1 time: Dentist"]
    assert anna[0].data["message"] == "10:00–11:00 · Test"
    assert [a["title"] for a in ben[0].data["data"]["actions"]] == [
        "Slumre 10 min",
        "Slumre 1 t",
        "Ferdig",
    ]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_options_reach_engine_and_notifier(
    hass: HomeAssistant, calendar: Any
) -> None:
    entry = standard_entry(
        hass, default_devices=["ben", "gone"], fallback_device="gone", snooze_short=5
    )
    await setup(hass, entry)
    engine = entry.runtime_data.engine
    assert engine.config.calendars == (CAL,)
    assert engine.config.aliases == ("anna", "ben")
    assert engine.config.default_devices == ("ben",)  # "gone" has no subentry
    assert engine.config.fallback_device is None
    assert entry.runtime_data.notifier.snooze_minutes == (5, 60)
    assert entry.runtime_data.notifier.devices["ben"].language == "nb"
    assert engine.config.all_day_time == time(18, 0)  # option not set: the default


@pytest.mark.parametrize(
    ("value", "expected"),
    [("07:45:00", time(7, 45)), ("19:30", time(19, 30)), ("garbage", time(18, 0))],
)
async def test_all_day_time_option(
    hass: HomeAssistant, calendar: Any, value: str, expected: time
) -> None:
    entry = standard_entry(hass, all_day_time=value)
    await setup(hass, entry)
    assert entry.runtime_data.engine.config.all_day_time == expected


async def test_all_day_reminder_at_all_day_time(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    """Bin day: "#remind 1d" on an all-day event comes the evening before."""
    anna = async_mock_service(hass, "notify", "mobile_app_annas_phone")
    async_mock_service(hass, "notify", "mobile_app_bens_phone")
    await add_event(
        hass, freezer, calendar, "Bin day", date(2026, 11, 3), "#remind 1d @anna"
    )
    entry = standard_entry(hass)
    await setup(hass, entry)
    await advance(hass, freezer, oslo(2026, 11, 2, 17, 59, 58))
    assert anna == []
    await advance(hass, freezer, oslo(2026, 11, 2, 18, 0))
    assert [c.data["title"] for c in anna] == ["⏰ Tomorrow: Bin day"]
    assert anna[0].data["message"] == "Tue 3 Nov (all day) · Test"


async def test_options_change_reloads(hass: HomeAssistant, calendar: Any) -> None:
    entry = standard_entry(hass)
    await setup(hass, entry)
    before = entry.runtime_data.engine
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "default_devices": ["anna"]}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.engine is not before
    assert entry.runtime_data.engine.config.default_devices == ("anna",)


async def test_removing_a_device_reloads(hass: HomeAssistant, calendar: Any) -> None:
    entry = standard_entry(hass)
    await setup(hass, entry)
    ben = next(s for s in entry.subentries.values() if s.unique_id == "ben")
    hass.config_entries.async_remove_subentry(entry, ben.subentry_id)
    await hass.async_block_till_done()
    assert set(entry.runtime_data.notifier.devices) == {"anna"}
    assert entry.runtime_data.engine.config.default_devices == ("anna",)


async def test_entry_from_0_2_0_is_not_migrated(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, version=1, data={"calendars": [CAL]})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_remove_entry_forgets_state(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    calendar: Any,
    hass_storage: dict[str, Any],
) -> None:
    async_mock_service(hass, "notify", "mobile_app_annas_phone")
    async_mock_service(hass, "notify", "mobile_app_bens_phone")
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h"
    )
    entry = standard_entry(hass)
    await setup(hass, entry)
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    assert ENGINE_STORAGE_KEY in hass_storage
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ENGINE_STORAGE_KEY not in hass_storage
