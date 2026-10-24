"""Engine tests against a real local_calendar entity, with frozen time.

They cover the reminder behaviour (see the README) that
doesn't need the notifier: timing, push scheduling, keys, restarts, snooze,
recurring events, 4-week offsets and late handling.
"""

import json
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.calendar.const import DATA_COMPONENT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
)

from custom_components.calendar_reminders.const import BUS_EVENT_FIRED
from custom_components.calendar_reminders.engine import (
    CalendarItem,
    Delivery,
    EngineConfig,
    ReminderEngine,
    parse_event,
    reminder_key,
    reminders_for_event,
)
from custom_components.calendar_reminders.remind_line import Offset, Unit

from .common import CAL, OSLO, START, add_event, advance, find_uid, oslo, settle

CONFIG = EngineConfig(
    calendars=(CAL,),
    aliases=("anna", "ben", "kitchen"),
    default_devices=("anna", "ben"),
    fallback_device="anna",
)


class Recorder:
    """Stands in for the notifier."""

    def __init__(self) -> None:
        self.deliveries: list[Delivery] = []

    async def __call__(self, delivery: Delivery) -> None:
        self.deliveries.append(delivery)

    def summary(self) -> list[tuple[str, tuple[str, ...], bool, bool]]:
        return [
            (d.reminder.summary, d.devices, d.late, d.snoozed) for d in self.deliveries
        ]


async def start_engine(
    hass: HomeAssistant, send: Recorder, config: EngineConfig = CONFIG
) -> ReminderEngine:
    engine = ReminderEngine(hass, config, send)
    await engine.async_start()
    await hass.async_block_till_done()
    return engine


# --- timing and recipients ----------------------------------------------------


async def test_fires_on_time_to_chosen_device(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h @anna"
    )
    send = Recorder()
    engine = await start_engine(hass, send)

    due = engine.next_due()
    assert due is not None
    assert due[0] == oslo(2026, 11, 2, 9, 0)

    await advance(hass, freezer, oslo(2026, 11, 2, 8, 59, 58))
    assert send.deliveries == []
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    assert send.summary() == [("Dentist", ("anna",), False, False)]
    assert send.deliveries[0].reminder.fire_at == oslo(2026, 11, 2, 9, 0)
    assert engine.next_due() is None
    await engine.async_stop()


async def test_line_without_device_goes_to_defaults(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass, freezer, calendar, "Gym", oslo(2026, 11, 2, 10, 0), "#remind 30m !"
    )
    send = Recorder()
    engine = await start_engine(hass, send)
    (reminder,) = engine.reminders.values()
    assert reminder.devices == ("anna", "ben")
    assert reminder.important
    await engine.async_stop()


async def test_unknown_device_goes_to_fallback_and_is_reported_without_title(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass,
        freezer,
        calendar,
        "Secret meeting",
        oslo(2026, 11, 2, 10, 0),
        "#remind 1h @bob",
    )
    engine = await start_engine(hass, Recorder())
    (reminder,) = engine.reminders.values()
    assert reminder.devices == ("anna",)
    assert reminder.unknown_devices == ("bob",)
    diag = engine.diagnostics()
    assert diag["unknown_tokens"][0]["tokens"] == ("@bob",)
    assert "Secret" not in json.dumps(diag)
    await engine.async_stop()


@pytest.mark.parametrize(
    "description", [None, "Notes only", "#remind off", "#remind @ben"]
)
async def test_no_active_line_no_reminder(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    calendar: Any,
    description: str | None,
) -> None:
    await add_event(
        hass, freezer, calendar, "Plain", oslo(2026, 11, 2, 10, 0), description
    )
    engine = await start_engine(hass, Recorder())
    assert engine.reminders == {}
    assert engine.diagnostics()["calendars"][CAL]["events"] == 1
    await engine.async_stop()


async def test_all_day_event_fixed_time(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass,
        freezer,
        calendar,
        "Bins",
        date(2026, 11, 3),
        "#remind 1d@18:00 0d@07:30 @kitchen",
    )
    send = Recorder()
    engine = await start_engine(hass, send)
    times = sorted(r.fire_at for r in engine.reminders.values())
    assert times == [oslo(2026, 11, 2, 18, 0), oslo(2026, 11, 3, 7, 30)]
    await advance(hass, freezer, oslo(2026, 11, 2, 18, 0))
    assert send.summary() == [("Bins", ("kitchen",), False, False)]
    await engine.async_stop()


async def test_four_week_offset_is_scheduled(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass, freezer, calendar, "Passport", oslo(2026, 11, 30, 9, 0), "#remind 4w 1w"
    )
    send = Recorder()
    engine = await start_engine(hass, send)
    times = sorted(r.fire_at for r in engine.reminders.values())
    assert times == [oslo(2026, 11, 2, 9, 0), oslo(2026, 11, 23, 9, 0)]
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    assert send.summary() == [("Passport", ("anna", "ben"), False, False)]
    await engine.async_stop()


async def test_bus_event_is_fired(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    events = async_capture_events(hass, BUS_EVENT_FIRED)
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h @ben"
    )
    engine = await start_engine(hass, Recorder())
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    assert len(events) == 1
    assert events[0].data["devices"] == ["ben"]
    assert events[0].data["unknown_devices"] == []
    assert events[0].data["offset"] == "1h"
    assert events[0].data["late"] is False
    await engine.async_stop()


# --- push scheduling, keys ----------------------------------------------------


async def test_event_saved_after_start_is_scheduled_by_push(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    """No rescan in between: the subscription alone picks it up."""
    engine = await start_engine(hass, Recorder())
    assert engine.reminders == {}
    assert engine.diagnostics()["calendars"][CAL]["subscribed"]
    await add_event(
        hass, freezer, calendar, "New", oslo(2026, 11, 2, 12, 0), "#remind 15m"
    )
    (reminder,) = engine.reminders.values()
    assert reminder.fire_at == oslo(2026, 11, 2, 11, 45)
    await engine.async_stop()


async def test_rename_does_not_resend(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    start = oslo(2026, 11, 2, 10, 0)
    await add_event(hass, freezer, calendar, "Dentist", start, "#remind 1h @anna")
    send = Recorder()
    engine = await start_engine(hass, send)
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    (key,) = engine.reminders
    uid = await find_uid(hass, calendar, "Dentist")

    await calendar.async_update_event(
        uid,
        {
            "dtstart": start,
            "dtend": start + timedelta(hours=1),
            "summary": "Dentist (kids)",
            "description": "#remind 1h @anna",
        },
    )
    await settle(hass, freezer)
    assert list(engine.reminders) == [key]
    assert len(send.deliveries) == 1
    await engine.async_stop()


async def test_move_creates_new_reminder(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h @anna"
    )
    send = Recorder()
    engine = await start_engine(hass, send)
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    (old_key,) = engine.reminders
    uid = await find_uid(hass, calendar, "Dentist")

    moved = oslo(2026, 11, 2, 11, 0)
    await calendar.async_update_event(
        uid,
        {
            "dtstart": moved,
            "dtend": moved + timedelta(hours=1),
            "summary": "Dentist",
            "description": "#remind 1h @anna",
        },
    )
    await settle(hass, freezer)
    (new_key,) = engine.reminders
    assert new_key != old_key
    await advance(hass, freezer, oslo(2026, 11, 2, 10, 0))
    assert len(send.deliveries) == 2
    await engine.async_stop()


async def test_recurring_occurrences_each_get_a_reminder(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass,
        freezer,
        calendar,
        "Standup",
        oslo(2026, 11, 2, 10, 0),
        "#remind 30m @anna",
        rrule="FREQ=DAILY;COUNT=3",
    )
    send = Recorder()
    engine = await start_engine(hass, send)
    assert len(engine.reminders) == 3
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 30))
    await advance(hass, freezer, oslo(2026, 11, 3, 9, 30))
    assert [d.reminder.fire_at for d in send.deliveries] == [
        oslo(2026, 11, 2, 9, 30),
        oslo(2026, 11, 3, 9, 30),
    ]
    await engine.async_stop()


# --- restarts, late, missed ---------------------------------------------------


async def test_restart_at_reminder_time_sends_once_marked_late(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h @anna"
    )
    engine = await start_engine(hass, Recorder())
    await engine.async_stop()  # "HA is down" across 09:00

    await advance(hass, freezer, oslo(2026, 11, 2, 9, 20))
    send = Recorder()
    engine = await start_engine(hass, send)
    assert send.summary() == [("Dentist", ("anna",), True, False)]
    await engine.async_stop()

    await advance(hass, freezer, oslo(2026, 11, 2, 9, 25))
    send = Recorder()
    engine = await start_engine(hass, send)
    assert send.deliveries == []
    await engine.async_stop()


async def test_reminder_missed_when_event_started_meanwhile(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h @anna"
    )
    await advance(hass, freezer, oslo(2026, 11, 2, 10, 5))
    send = Recorder()
    engine = await start_engine(hass, send)
    assert send.deliveries == []
    assert engine.diagnostics()["missed"] == 1
    await engine.async_stop()


async def test_line_added_after_reminder_time_sends_late(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    send = Recorder()
    engine = await start_engine(hass, send)
    await add_event(
        hass, freezer, calendar, "Soon", oslo(2026, 11, 2, 8, 30), "#remind 1h @anna"
    )
    assert send.summary() == [("Soon", ("anna",), True, False)]
    await engine.async_stop()


async def test_send_error_is_counted_and_not_retried(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    async def broken(_delivery: Delivery) -> None:
        raise RuntimeError("notify service missing")

    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h @anna"
    )
    engine = await start_engine(hass, broken)  # type: ignore[arg-type]
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    await engine.async_rescan()
    await hass.async_block_till_done()
    assert engine.diagnostics()["send_errors"] == 1
    assert engine.diagnostics()["fired"] == 1
    await engine.async_stop()


# --- snooze and done ----------------------------------------------------------


async def test_snooze_survives_restart_and_goes_to_that_device_only(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass,
        freezer,
        calendar,
        "Dentist",
        oslo(2026, 11, 2, 10, 0),
        "#remind 1h @anna @ben",
    )
    send = Recorder()
    engine = await start_engine(hass, send)
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    (key,) = engine.reminders
    assert await engine.async_snooze(key, "ben", 10)
    await engine.async_stop()

    await advance(hass, freezer, oslo(2026, 11, 2, 9, 5))
    send = Recorder()
    engine = await start_engine(hass, send)
    assert send.deliveries == []
    due = engine.next_due()
    assert due is not None
    assert due[0] == oslo(2026, 11, 2, 9, 10)
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 10))
    assert send.summary() == [("Dentist", ("ben",), False, True)]
    await engine.async_stop()


async def test_done_cancels_snooze(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h @anna"
    )
    send = Recorder()
    engine = await start_engine(hass, send)
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    (key,) = engine.reminders
    assert await engine.async_snooze(key, "anna", 60)
    assert engine.diagnostics()["snoozes"] == 1
    assert await engine.async_done(key, "anna")
    assert engine.diagnostics()["snoozes"] == 0
    await advance(hass, freezer, oslo(2026, 11, 2, 10, 0))
    assert len(send.deliveries) == 1
    assert not await engine.async_snooze("nope", "anna", 10)
    await engine.async_stop()


async def test_snooze_dropped_when_event_deleted(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h @anna"
    )
    send = Recorder()
    engine = await start_engine(hass, send)
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    (key,) = engine.reminders
    await engine.async_snooze(key, "anna", 10)
    await calendar.async_delete_event(await find_uid(hass, calendar, "Dentist"))
    await settle(hass, freezer)
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 10))
    assert len(send.deliveries) == 1
    assert engine.diagnostics()["snoozes"] == 0
    await engine.async_stop()


# --- reading calendars --------------------------------------------------------


async def test_rescan_fallback_to_action_without_entity_api(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    calendar: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h @anna"
    )
    engine = ReminderEngine(hass, CONFIG, Recorder())
    monkeypatch.setattr(engine, "_entity", lambda _calendar: object())
    await engine.async_start()
    await hass.async_block_till_done()
    (reminder,) = engine.reminders.values()
    # The action returns no UID, so the title stands in for it.
    item = CalendarItem(
        CAL, "Dentist", oslo(2026, 11, 2, 10, 0), oslo(2026, 11, 2, 11, 0)
    )
    assert reminder.key == reminder_key(item, Offset(Unit.MINUTES, 60))
    assert not engine.diagnostics()["calendars"][CAL]["subscribed"]
    await engine.async_stop()


async def test_rescan_every_15_minutes(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    calendar: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = ReminderEngine(hass, CONFIG, Recorder())
    monkeypatch.setattr(engine, "_subscribe", lambda *_args: None)  # push unavailable
    await engine.async_start()
    await hass.async_block_till_done()
    await add_event(
        hass, freezer, calendar, "Later", oslo(2026, 11, 2, 12, 0), "#remind 1h"
    )
    assert engine.reminders == {}
    await advance(hass, freezer, START + timedelta(minutes=15, seconds=5))
    assert len(engine.reminders) == 1
    await engine.async_stop()


async def test_missing_calendar_is_reported(hass: HomeAssistant, calendar: Any) -> None:
    config = EngineConfig(("calendar.nope", CAL), ("anna",), ("anna",))
    engine = await start_engine(hass, Recorder(), config)
    diag = engine.diagnostics()["calendars"]
    assert diag["calendar.nope"] == {
        "events": 0,
        "subscribed": False,
        "unavailable": True,
    }
    assert diag[CAL]["unavailable"] is False
    await engine.async_stop()


# --- pure helpers -------------------------------------------------------------


def test_parse_event_formats() -> None:
    timed = parse_event(
        CAL,
        {
            "start": "2026-11-02T10:00:00+01:00",
            "end": "2026-11-02T11:00:00+01:00",
            "summary": "A",
            "status": "tentative",
            "uid": "u1",
        },
        OSLO,
    )
    assert timed is not None
    assert timed.start == oslo(2026, 11, 2, 10, 0)
    assert timed.tentative
    assert not timed.all_day

    naive = parse_event(
        CAL, {"start": "2026-11-02T10:00:00", "end": "2026-11-02T11:00:00"}, OSLO
    )
    assert naive is not None
    assert naive.start == oslo(2026, 11, 2, 10, 0)

    all_day = parse_event(
        CAL, {"start": "2026-11-03", "end": "2026-11-04", "summary": "B"}, OSLO
    )
    assert all_day is not None
    assert all_day.all_day
    assert all_day.start == date(2026, 11, 3)

    objects = parse_event(
        CAL, {"start": datetime(2026, 11, 2, 10, 0), "end": date(2026, 11, 3)}, OSLO
    )
    assert objects is not None
    assert objects.start == oslo(2026, 11, 2, 10, 0)

    assert parse_event(CAL, {"start": "garbage", "end": "2026-11-04"}, OSLO) is None
    assert (
        parse_event(CAL, {"start": "2026-11-02Tgarbage", "end": "2026-11-04"}, OSLO)
        is None
    )
    assert parse_event(CAL, {"start": 12, "end": "2026-11-04"}, OSLO) is None


def test_keys_without_uid_use_title_and_start() -> None:
    offset = Offset(Unit.DAYS_AT, 1, time(18, 0))
    a = CalendarItem(CAL, "Bin day", date(2026, 11, 3), date(2026, 11, 4))
    same = CalendarItem(
        CAL, "Bin day", date(2026, 11, 3), date(2026, 11, 4), description="x"
    )
    other_title = CalendarItem(CAL, "Paper", date(2026, 11, 3), date(2026, 11, 4))
    other_day = CalendarItem(CAL, "Bin day", date(2026, 11, 17), date(2026, 11, 18))
    assert reminder_key(a, offset) == reminder_key(same, offset)
    assert reminder_key(a, offset) != reminder_key(other_title, offset)
    assert reminder_key(a, offset) != reminder_key(other_day, offset)


def test_keys_with_uid_ignore_title_but_not_occurrence() -> None:
    offset = Offset(Unit.MINUTES, 60)
    start = oslo(2026, 11, 2, 10, 0)
    a = CalendarItem(CAL, "A", start, start, uid="u1", recurrence_id="20261102T100000")
    renamed = CalendarItem(
        CAL, "B", start, start, uid="u1", recurrence_id="20261102T100000"
    )
    other_occurrence = CalendarItem(
        CAL, "A", start, start, uid="u1", recurrence_id="20261103T100000"
    )
    same_instant_utc = CalendarItem(
        CAL,
        "A",
        start.astimezone(ZoneInfo("UTC")),
        start,
        uid="u1",
        recurrence_id="20261102T100000",
    )
    assert reminder_key(a, offset) == reminder_key(renamed, offset)
    assert reminder_key(a, offset) == reminder_key(same_instant_utc, offset)
    assert reminder_key(a, offset) != reminder_key(other_occurrence, offset)


# --- housekeeping and error paths ---------------------------------------------


async def test_daily_resubscribe_keeps_push_working(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    engine = await start_engine(hass, Recorder())
    await advance(hass, freezer, oslo(2026, 11, 3, 0, 5))
    assert engine.diagnostics()["calendars"][CAL]["subscribed"]
    await add_event(
        hass, freezer, calendar, "After", oslo(2026, 11, 3, 12, 0), "#remind 1h"
    )
    assert len(engine.reminders) == 1
    await engine.async_stop()


async def test_fired_state_is_pruned_and_not_resent(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h @anna"
    )
    send = Recorder()
    engine = await start_engine(hass, send)
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    assert engine.diagnostics()["fired"] == 1
    await advance(hass, freezer, oslo(2026, 11, 4, 10, 15))  # a rescan runs
    assert engine.diagnostics()["fired"] == 0
    assert engine.reminders == {}  # outside the window now
    assert len(send.deliveries) == 1
    await engine.async_stop()


async def test_listeners_and_done_on_other_device(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    await add_event(
        hass,
        freezer,
        calendar,
        "Dentist",
        oslo(2026, 11, 2, 10, 0),
        "#remind 1h @anna @ben",
    )
    engine = await start_engine(hass, Recorder())
    calls: list[None] = []
    unsub = engine.async_add_listener(lambda: calls.append(None))
    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    assert calls  # the fire notified
    (key,) = engine.reminders
    before = len(calls)
    await engine.async_snooze(key, "ben", 10)
    assert await engine.async_done(key, "anna")  # anna had no snooze: ben's stays
    assert engine.diagnostics()["snoozes"] == 1
    assert len(calls) == before + 2
    unsub()
    await engine.async_done(key, "ben")
    assert len(calls) == before + 2
    await engine.async_stop()


async def test_failed_push_and_failed_fetch_keep_last_events(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    calendar: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h"
    )
    engine = await start_engine(hass, Recorder())
    engine._on_push(CAL, None)  # the entity reports a read error
    assert len(engine.reminders) == 1

    async def fail(*_args: Any) -> None:
        raise HomeAssistantError("backend down")

    monkeypatch.setattr(engine, "_async_fetch", fail)
    await engine.async_rescan()
    await hass.async_block_till_done()
    assert len(engine.reminders) == 1
    assert engine.diagnostics()["calendars"][CAL]["unavailable"]
    await engine.async_stop()


async def test_fetch_uses_action_when_calendar_component_missing(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    calendar: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_event(
        hass, freezer, calendar, "Dentist", oslo(2026, 11, 2, 10, 0), "#remind 1h"
    )
    engine = ReminderEngine(hass, CONFIG, Recorder())
    component = hass.data.pop(DATA_COMPONENT)
    try:
        events = await engine._async_fetch(CAL, START, START + timedelta(days=1))
    finally:
        hass.data[DATA_COMPONENT] = component
    assert events is not None
    assert [e["summary"] for e in events] == ["Dentist"]
    assert "uid" not in events[0]


async def test_wall_clock_offset_across_dst_in_engine(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    """25 Oct 2026 Oslo falls back: 1d before 10:00 CET is 10:00 CEST (25 h)."""
    await advance(hass, freezer, datetime(2026, 10, 24, 8, 0, tzinfo=OSLO))
    await add_event(
        hass, freezer, calendar, "Brunch", oslo(2026, 10, 25, 10, 0), "#remind 1d 2h"
    )
    engine = await start_engine(hass, Recorder())
    times = sorted(r.fire_at for r in engine.reminders.values())
    assert times == [oslo(2026, 10, 24, 10, 0), oslo(2026, 10, 25, 8, 0)]
    await engine.async_stop()


@pytest.mark.parametrize(
    ("line", "fallback", "devices", "unknown"),
    [
        ("#remind 1h", "anna", ("anna", "ben"), ()),  # no @: the defaults
        ("#remind 1h @kitchen", "anna", ("kitchen",), ()),
        ("#remind 1h @bob", "anna", ("anna",), ("bob",)),  # typo: fallback only
        ("#remind 1h @ben @bbo", "anna", ("ben", "anna"), ("bbo",)),  # plus fallback
        ("#remind 1h @anna @bob", "anna", ("anna",), ("bob",)),  # not twice
        ("#remind 1h @bob @carl", "anna", ("anna",), ("bob", "carl")),
        ("#remind 1h soon", "anna", ("anna", "ben"), ()),  # not a device: defaults
        ("#remind 1h @bob", None, None, None),  # no fallback set: nobody
        ("#remind 1h @ben @bob", None, ("ben",), ("bob",)),
    ],
)
def test_recipients(
    line: str,
    fallback: str | None,
    devices: tuple[str, ...] | None,
    unknown: tuple[str, ...] | None,
) -> None:
    config = EngineConfig((CAL,), ("anna", "ben", "kitchen"), ("anna", "ben"), fallback)
    item = CalendarItem(
        CAL, "A", oslo(2026, 11, 2, 10, 0), oslo(2026, 11, 2, 11, 0), line
    )
    reminders, _tokens = reminders_for_event(item, config, OSLO)
    if devices is None:
        assert reminders == []
        return
    (reminder,) = reminders
    assert (reminder.devices, reminder.unknown_devices) == (devices, unknown)


@pytest.mark.parametrize(
    ("line", "all_day_time", "expected"),
    [
        ("#remind 1d", time(18, 0), [oslo(2026, 11, 3, 18, 0)]),
        (
            "#remind 2d 1w",
            time(18, 0),
            [oslo(2026, 10, 28, 18, 0), oslo(2026, 11, 2, 18, 0)],
        ),
        ("#remind 0d", time(7, 0), [oslo(2026, 11, 4, 7, 0)]),
        (
            "#remind 1d@07:30",
            time(18, 0),
            [oslo(2026, 11, 3, 7, 30)],
        ),  # its own time wins
        (
            "#remind 1d 1d@18:00",
            time(18, 0),
            [oslo(2026, 11, 3, 18, 0)],
        ),  # one, not two
        (
            "#remind 1d 1d@07:30",
            time(18, 0),
            [oslo(2026, 11, 3, 7, 30), oslo(2026, 11, 3, 18, 0)],
        ),
        (
            "#remind 1h",
            time(18, 0),
            [oslo(2026, 11, 3, 23, 0)],
        ),  # minutes/hours: from midnight
        ("#remind 1d", None, [oslo(2026, 11, 3, 0, 0)]),  # no all-day time: midnight
    ],
)
def test_all_day_time_for_plain_days(
    line: str, all_day_time: time | None, expected: list[datetime]
) -> None:
    config = EngineConfig((CAL,), ("anna",), ("anna",), all_day_time=all_day_time)
    item = CalendarItem(CAL, "Bins", date(2026, 11, 4), date(2026, 11, 5), line)
    reminders, _ = reminders_for_event(item, config, OSLO)
    assert sorted(r.fire_at for r in reminders) == expected


def test_all_day_time_shows_in_offset_and_not_on_timed_events() -> None:
    config = EngineConfig((CAL,), ("anna",), ("anna",), all_day_time=time(18, 0))
    all_day = CalendarItem(
        CAL, "Bins", date(2026, 11, 4), date(2026, 11, 5), "#remind 1d"
    )
    (reminder,) = reminders_for_event(all_day, config, OSLO)[0]
    assert reminder.offset.token() == "1d@18:00"
    timed = CalendarItem(
        CAL, "Dentist", oslo(2026, 11, 4, 10, 0), oslo(2026, 11, 4, 11, 0), "#remind 1d"
    )
    (reminder,) = reminders_for_event(timed, config, OSLO)[0]
    assert reminder.fire_at == oslo(2026, 11, 3, 10, 0)
    assert reminder.offset.token() == "1d"
