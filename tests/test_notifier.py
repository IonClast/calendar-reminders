"""Notifier tests: payload, texts in en/nb, the unknown-recipient note, buttons."""

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.calendar_reminders.engine import (
    CalendarItem,
    Delivery,
    EngineConfig,
    Reminder,
    ReminderEngine,
    reminders_for_event,
)
from custom_components.calendar_reminders.notifier import (
    Device,
    Notifier,
    action_id,
    build_message,
    parse_action,
    time_span,
    when_phrase,
)

from .common import CAL, OSLO, add_event, advance, oslo

ANNA = Device("anna", "mobile_app_annas_phone", "en")
BEN = Device("ben", "notify.mobile_app_bens_phone", "nb")
KITCHEN = Device("kitchen", "mobile_app_kitchen_tablet", "nb")
DEVICES = {d.alias: d for d in (ANNA, BEN, KITCHEN)}
CONFIG = EngineConfig((CAL,), tuple(DEVICES), ("anna", "ben"), fallback_device="anna")
NOW = oslo(2026, 11, 2, 9, 0)  # Monday
TODAY = NOW.date()


def reminder(
    start: datetime | date,
    end: datetime | date | None = None,
    line: str = "#remind 1h @anna",
    *,
    summary: str = "Dentist",
    location: str | None = None,
    tentative: bool = False,
) -> Reminder:
    if end is None:
        end = start + (
            timedelta(hours=1) if isinstance(start, datetime) else timedelta(days=1)
        )
    item = CalendarItem(
        CAL, summary, start, end, line, location=location, uid="u1", tentative=tentative
    )
    found, _ = reminders_for_event(item, CONFIG, OSLO)
    return found[0]


def build(rem: Reminder, device: Device = ANNA, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("calendar_name", "Family calendar")
    return build_message(rem, device, tz=OSLO, **kwargs)


# --- payload ------------------------------------------------------------------


def test_payload_english() -> None:
    rem = reminder(oslo(2026, 11, 2, 10, 0), location="Main Street Clinic")
    data = build(rem)
    assert data["title"] == "⏰ In 1 hour: Dentist"
    assert data["message"] == "10:00–11:00 · Main Street Clinic · Family calendar"
    assert data["data"] == {
        "tag": f"calrem-{rem.key}",
        "group": "calendar-reminders",
        "channel": "Calendar reminders",
        "importance": "high",
        "priority": "high",
        "ttl": 0,
        "clickAction": "/calendar",
        "notification_icon": "mdi:calendar-clock",
        "vibrationPattern": "0, 300, 200, 300",
        "actions": [
            {"action": f"CALREM_SNOOZE10_{rem.key}_anna", "title": "Snooze 10 min"},
            {"action": f"CALREM_SNOOZE60_{rem.key}_anna", "title": "Snooze 1 h"},
            {"action": f"CALREM_DONE_{rem.key}_anna", "title": "Done"},
        ],
    }


def test_payload_norwegian() -> None:
    rem = reminder(oslo(2026, 11, 3, 10, 0), line="#remind 1d @ben")
    data = build(rem, BEN)
    assert data["title"] == "⏰ I morgen: Dentist"
    assert data["message"] == "tir. 3. nov. 10:00–11:00 · Family calendar"
    assert [a["title"] for a in data["data"]["actions"]] == [
        "Slumre 10 min",
        "Slumre 1 t",
        "Ferdig",
    ]
    assert data["data"]["actions"][2]["action"] == f"CALREM_DONE_{rem.key}_ben"


def test_important_uses_alarm_stream() -> None:
    rem = reminder(oslo(2026, 11, 2, 10, 0), line="#remind 1h !")
    assert build(rem)["data"]["channel"] == "alarm_stream"


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        (ANNA, "⏰ In 40 min: Dentist (tentative) (late)"),
        (BEN, "⏰ Om 40 min: Dentist (foreløpig) (forsinket)"),
    ],
)
def test_tentative_and_late(device: Device, expected: str) -> None:
    rem = reminder(oslo(2026, 11, 2, 9, 40), tentative=True)
    assert build(rem, device, late=True)["title"] == expected


def test_unknown_language_falls_back_to_english() -> None:
    rem = reminder(oslo(2026, 11, 2, 10, 0))
    assert (
        build(rem, Device("x", "mobile_app_x", "de"))["title"]
        == "⏰ In 1 hour: Dentist"
    )


def test_custom_snooze_lengths() -> None:
    rem = reminder(oslo(2026, 11, 2, 10, 0))
    data = build(rem, snooze_minutes=(5, 30, 120))
    titles = [a["title"] for a in data["data"]["actions"]]
    assert titles == ["Snooze 5 min", "Snooze 30 min", "Snooze 2 h", "Done"]


# --- unknown-recipient note ---------------------------------------------------


def test_unknown_note_only_on_fallback_copy() -> None:
    rem = reminder(oslo(2026, 11, 2, 10, 0), line="#remind 1h @ben @bbo @carl")
    assert rem.devices == ("ben", "anna")
    assert rem.unknown_devices == ("bbo", "carl")
    anna = build(rem, ANNA, note_unknown=True)
    assert anna["message"] == (
        "10:00–11:00 · Family calendar\n"
        "Unknown recipient: @bbo, @carl. Check the #remind line."
    )
    assert "\n" not in build(rem, BEN)["message"]


def test_unknown_note_in_norwegian() -> None:
    rem = reminder(oslo(2026, 11, 2, 10, 0), line="#remind 1h @bob")
    data = build(rem, BEN, note_unknown=True)
    assert data["message"].endswith("\nUkjent mottaker: @bob. Sjekk #remind-linjen.")


def test_no_note_without_unknown_devices() -> None:
    rem = reminder(oslo(2026, 11, 2, 10, 0))
    assert "\n" not in build(rem, ANNA, note_unknown=True)["message"]


# --- texts --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "now", "en", "nb"),
    [
        (oslo(2026, 11, 2, 9, 0), NOW, "Now", "Nå"),
        (oslo(2026, 11, 2, 9, 0, 20), NOW, "Now", "Nå"),
        (oslo(2026, 11, 2, 8, 58), NOW, "Started", "Startet"),
        (oslo(2026, 11, 2, 9, 40), NOW, "In 40 min", "Om 40 min"),
        (oslo(2026, 11, 2, 9, 59, 40), NOW, "In 1 hour", "Om 1 time"),
        (oslo(2026, 11, 2, 10, 30), NOW, "In 1 h 30 min", "Om 1 t 30 min"),
        (oslo(2026, 11, 2, 12, 0), NOW, "In 3 hours", "Om 3 timer"),
        (oslo(2026, 11, 2, 20, 0), NOW, "In 11 hours", "Om 11 timer"),
        (oslo(2026, 11, 2, 21, 30), NOW, "Today", "I dag"),
        (oslo(2026, 11, 3, 10, 0), NOW, "Tomorrow", "I morgen"),
        (oslo(2026, 11, 3, 7, 0), oslo(2026, 11, 2, 22, 0), "In 9 hours", "Om 9 timer"),
        (oslo(2026, 11, 5, 10, 0), NOW, "In 3 days", "Om 3 dager"),
        (oslo(2026, 11, 9, 10, 0), NOW, "In 1 week", "Om 1 uke"),
        (oslo(2026, 11, 16, 10, 0), NOW, "In 2 weeks", "Om 2 uker"),
        (date(2026, 11, 2), NOW, "Today", "I dag"),
        (date(2026, 11, 3), NOW, "Tomorrow", "I morgen"),
        (date(2026, 11, 1), NOW, "Started", "Startet"),
    ],
)
def test_when_phrase(start: datetime | date, now: datetime, en: str, nb: str) -> None:
    rem = reminder(start, line="#remind 0")
    assert when_phrase(rem, now, OSLO, "en") == en
    assert when_phrase(rem, now, OSLO, "nb") == nb


@pytest.mark.parametrize(
    ("start", "end", "en", "nb"),
    [
        (oslo(2026, 11, 2, 10, 0), None, "10:00–11:00", "10:00–11:00"),
        (
            oslo(2026, 11, 3, 10, 0),
            None,
            "Tue 3 Nov 10:00–11:00",
            "tir. 3. nov. 10:00–11:00",
        ),
        (
            oslo(2026, 11, 2, 23, 0),
            oslo(2026, 11, 3, 0, 0),
            "23:00–00:00",
            "23:00–00:00",
        ),
        (
            oslo(2026, 11, 3, 14, 0),
            oslo(2026, 11, 4, 10, 0),
            "Tue 3 Nov 14:00 – Wed 4 Nov 10:00",
            "tir. 3. nov. 14:00 – ons. 4. nov. 10:00",
        ),
        (oslo(2026, 11, 2, 10, 0), oslo(2026, 11, 2, 10, 0), "10:00", "10:00"),
        (date(2026, 11, 2), None, "All day", "Hele dagen"),
        (date(2026, 11, 3), None, "Tue 3 Nov (all day)", "tir. 3. nov. (hele dagen)"),
        (
            date(2026, 11, 3),
            date(2026, 11, 6),
            "Tue 3 Nov – Thu 5 Nov",
            "tir. 3. nov. – tor. 5. nov.",
        ),
        (
            oslo(2027, 1, 4, 10, 0),
            None,
            "Mon 4 Jan 2027 10:00–11:00",
            "man. 4. jan. 2027 10:00–11:00",
        ),
        (
            date(2027, 3, 2),
            None,
            "Tue 2 Mar 2027 (all day)",
            "tir. 2. mars 2027 (hele dagen)",
        ),
    ],
)
def test_time_span(
    start: datetime | date, end: datetime | date | None, en: str, nb: str
) -> None:
    rem = reminder(start, end, line="#remind 0")
    assert time_span(rem, TODAY, OSLO, "en") == en
    assert time_span(rem, TODAY, OSLO, "nb") == nb


def test_message_counts_down_from_send_time() -> None:
    """A snoozed or late reminder says how far away the event really is."""
    rem = reminder(oslo(2026, 11, 2, 10, 0))
    assert build(rem, now=oslo(2026, 11, 2, 9, 10))["title"] == "⏰ In 50 min: Dentist"


# --- action IDs ---------------------------------------------------------------


def test_action_round_trip() -> None:
    key = "0123456789abcdef"
    assert parse_action(action_id("SNOOZE10", key, "anna")) == (10, key, "anna")
    assert parse_action(action_id("SNOOZE60", key, "wall_panel")) == (
        60,
        key,
        "wall_panel",
    )
    assert parse_action(action_id("DONE", key, "ben")) == (None, key, "ben")


@pytest.mark.parametrize(
    "action",
    [
        "",
        "OPEN_GARAGE",
        "CALREM_SNOOZE_0123456789abcdef_anna",  # 0.2.0 style
        "CALREM_SNOOZE10_0123456789ABCDEF_anna",
        "CALREM_DONE_0123456789abcdef_ANNA",
        "CALREM_DONE_0123_anna",
        "CALREM_LATER_0123456789abcdef_anna",
    ],
)
def test_foreign_actions_are_ignored(action: str) -> None:
    assert parse_action(action) is None


# --- sending ------------------------------------------------------------------


async def test_send_one_call_per_device_in_its_language(hass: HomeAssistant) -> None:
    hass.states.async_set(CAL, "off", {"friendly_name": "Family calendar"})
    anna_calls = async_mock_service(hass, "notify", "mobile_app_annas_phone")
    ben_calls = async_mock_service(hass, "notify", "mobile_app_bens_phone")
    rem = reminder(
        datetime.now(OSLO) + timedelta(hours=2), line="#remind 1h @anna @ben"
    )
    notifier = Notifier(hass, DEVICES, fallback_device="anna")
    await notifier.async_send(Delivery(rem, rem.devices, late=False, snoozed=False))
    assert len(anna_calls) == len(ben_calls) == 1
    assert anna_calls[0].data["title"].startswith("⏰ In ")
    assert anna_calls[0].data["message"].endswith("· Family calendar")
    assert ben_calls[0].data["title"].startswith("⏰ Om ")
    assert anna_calls[0].data["data"]["tag"] == ben_calls[0].data["data"]["tag"]


async def test_send_reports_failures_but_reaches_the_rest(hass: HomeAssistant) -> None:
    anna_calls = async_mock_service(hass, "notify", "mobile_app_annas_phone")
    rem = reminder(
        datetime.now(OSLO) + timedelta(hours=2), line="#remind 1h @anna @ben"
    )
    devices = {"anna": ANNA, "ben": BEN}  # ben's notify action doesn't exist here
    notifier = Notifier(hass, devices)
    delivery = Delivery(rem, ("anna", "ben", "kitchen"), late=False, snoozed=False)
    with pytest.raises(HomeAssistantError, match=r"@kitchen: not configured.*@ben"):
        await notifier.async_send(delivery)
    assert len(anna_calls) == 1


# --- buttons ------------------------------------------------------------------


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, int | None]] = []

    async def async_snooze(self, key: str, device: str, minutes: int) -> bool:
        self.calls.append(("snooze", key, device, minutes))
        return True

    async def async_done(self, key: str, device: str) -> bool:
        self.calls.append(("done", key, device, None))
        return True


@pytest.mark.parametrize(
    ("verb", "expected"),
    [
        ("SNOOZE10", ("snooze", "ben", 10)),
        ("SNOOZE60", ("snooze", "ben", 60)),
        ("DONE", ("done", "ben", None)),
    ],
)
async def test_button_acts_and_clears_only_that_device(
    hass: HomeAssistant, verb: str, expected: tuple[str, str, int | None]
) -> None:
    anna_calls = async_mock_service(hass, "notify", "mobile_app_annas_phone")
    ben_calls = async_mock_service(hass, "notify", "mobile_app_bens_phone")
    engine = FakeEngine()
    notifier = Notifier(hass, DEVICES)
    unsub = notifier.async_attach(engine)  # type: ignore[arg-type]
    key = "0123456789abcdef"
    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": action_id(verb, key, "ben")}
    )
    await hass.async_block_till_done()
    verb_name, device, minutes = expected
    assert engine.calls == [(verb_name, key, device, minutes)]
    assert anna_calls == []
    assert [c.data for c in ben_calls] == [
        {"message": "clear_notification", "data": {"tag": f"calrem-{key}"}}
    ]
    unsub()


async def test_other_actions_and_unknown_devices_are_ignored(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    engine = FakeEngine()
    notifier = Notifier(hass, {"anna": ANNA})  # no notify action registered for anna
    unsub = notifier.async_attach(engine)  # type: ignore[arg-type]
    key = "0123456789abcdef"
    hass.bus.async_fire("mobile_app_notification_action", {"action": "OPEN_GARAGE"})
    hass.bus.async_fire("mobile_app_notification_action", {})
    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": action_id("DONE", key, "nobody")}
    )
    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": action_id("DONE", key, "anna")}
    )
    await hass.async_block_till_done()
    assert engine.calls == [("done", key, "nobody", None), ("done", key, "anna", None)]
    assert "Could not clear" in caplog.text  # anna's notify action is missing
    unsub()


async def test_buttons_before_attach_do_nothing(hass: HomeAssistant) -> None:
    notifier = Notifier(hass, DEVICES)
    await notifier._async_on_action(
        type(
            "E", (), {"data": {"action": action_id("DONE", "0123456789abcdef", "anna")}}
        )()
    )


# --- end to end with the engine -----------------------------------------------


async def test_end_to_end_fire_snooze_done(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, calendar: Any
) -> None:
    anna_calls = async_mock_service(hass, "notify", "mobile_app_annas_phone")
    ben_calls = async_mock_service(hass, "notify", "mobile_app_bens_phone")
    notifier = Notifier(hass, DEVICES, fallback_device="anna")
    engine = ReminderEngine(hass, CONFIG, notifier.async_send)
    unsub = notifier.async_attach(engine)
    await add_event(
        hass,
        freezer,
        calendar,
        "Dentist",
        oslo(2026, 11, 2, 10, 0),
        "#remind 1h @anna @ben",
    )
    await engine.async_start()
    await hass.async_block_till_done()

    await advance(hass, freezer, oslo(2026, 11, 2, 9, 0))
    assert [c.data["title"] for c in anna_calls] == ["⏰ In 1 hour: Dentist"]
    assert [c.data["title"] for c in ben_calls] == ["⏰ Om 1 time: Dentist"]
    (key,) = engine.reminders
    tag = f"calrem-{key}"

    await advance(hass, freezer, oslo(2026, 11, 2, 9, 1))
    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": action_id("SNOOZE10", key, "ben")}
    )
    await hass.async_block_till_done()
    assert ben_calls[-1].data == {"message": "clear_notification", "data": {"tag": tag}}

    await advance(hass, freezer, oslo(2026, 11, 2, 9, 11))
    assert ben_calls[-1].data["title"] == "⏰ Om 49 min: Dentist"
    assert ben_calls[-1].data["data"]["tag"] == tag
    assert len(anna_calls) == 1  # the snooze went to Ben's phone only

    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": action_id("DONE", key, "anna")}
    )
    await hass.async_block_till_done()
    assert anna_calls[-1].data == {
        "message": "clear_notification",
        "data": {"tag": tag},
    }
    assert len(ben_calls) == 3
    unsub()
    await engine.async_stop()
