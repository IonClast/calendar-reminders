"""Notifier for calendar_reminders.

- Sends each ``Delivery`` from the engine with the legacy
  ``notify.mobile_app_*`` action (notify entities can't carry buttons), one
  call per device, in that device's language (en or nb).
- Payload: tag (one per reminder, so a snooze replaces it), group, channel
  (``alarm_stream`` when important), high importance and priority, ttl 0,
  click opens /calendar, and three buttons: Snooze x, Snooze y, Done.
- The text counts down from the moment it is sent ("In 40 min"), so late and
  snoozed reminders are right too.
- The fallback device's copy says which ``@names`` in the line were unknown.
- Buttons: each action ID carries the reminder key and the device alias, so
  Snooze and Done act on the phone that was tapped and clear only that phone.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    COUNTDOWN_HOURS,
    DEFAULT_SNOOZE_MINUTES,
    MOBILE_APP_ACTION_EVENT,
    NOTIFY_CHANNEL,
    NOTIFY_CHANNEL_IMPORTANT,
    NOTIFY_CLICK_ACTION,
    NOTIFY_GROUP,
    NOTIFY_ICON,
    NOTIFY_TAG_PREFIX,
)

if TYPE_CHECKING:
    from .engine import Delivery, Reminder, ReminderEngine

_LOGGER = logging.getLogger(__name__)

_ACTION_RE = re.compile(
    r"^CALREM_(?:SNOOZE(\d{1,4})|DONE)_([0-9a-f]{16})_([a-z0-9_]+)$"
)

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "now": "Now",
        "started": "Started",
        "in_min": "In {m} min",
        "in_hour": "In 1 hour",
        "in_hours": "In {h} hours",
        "in_h_min": "In {h} h {m} min",
        "today": "Today",
        "tomorrow": "Tomorrow",
        "in_days": "In {n} days",
        "in_week": "In 1 week",
        "in_weeks": "In {n} weeks",
        "all_day": "All day",
        "all_day_suffix": " (all day)",
        "late": " (late)",
        "tentative": " (tentative)",
        "unknown": "Unknown recipient: {names}. Check the #remind line.",
        "snooze": "Snooze {d}",
        "done": "Done",
        "hours_unit": "h",
    },
    "nb": {
        "now": "Nå",
        "started": "Startet",
        "in_min": "Om {m} min",
        "in_hour": "Om 1 time",
        "in_hours": "Om {h} timer",
        "in_h_min": "Om {h} t {m} min",
        "today": "I dag",
        "tomorrow": "I morgen",
        "in_days": "Om {n} dager",
        "in_week": "Om 1 uke",
        "in_weeks": "Om {n} uker",
        "all_day": "Hele dagen",
        "all_day_suffix": " (hele dagen)",
        "late": " (forsinket)",
        "tentative": " (foreløpig)",
        "unknown": "Ukjent mottaker: {names}. Sjekk #remind-linjen.",
        "snooze": "Slumre {d}",
        "done": "Ferdig",
        "hours_unit": "t",
    },
}
_WEEKDAYS = {
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "nb": ("man.", "tir.", "ons.", "tor.", "fre.", "lør.", "søn."),
}
_MONTHS = {
    "en": (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ),
    "nb": (
        "jan.", "feb.", "mars", "apr.", "mai", "juni",
        "juli", "aug.", "sep.", "okt.", "nov.", "des.",
    ),
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class Device:
    """A phone or tablet that can receive reminders."""

    alias: str  # as used in "#remind ... @alias"
    notify_action: str  # legacy notify action, e.g. "mobile_app_annas_phone"
    language: str = "en"  # "en" or "nb"


def action_id(verb: str, key: str, alias: str) -> str:
    """Button action ID, e.g. ``CALREM_SNOOZE10_<key>_anna``."""
    return f"CALREM_{verb}_{key}_{alias}"


def parse_action(action: str) -> tuple[int | None, str, str] | None:
    """(snooze minutes or None for Done, key, alias), or None if not ours."""
    if not (m := _ACTION_RE.match(action)):
        return None
    return (int(m[1]) if m[1] else None), m[2], m[3]


def tag_for(key: str) -> str:
    return f"{NOTIFY_TAG_PREFIX}{key}"


def build_message(
    reminder: Reminder,
    device: Device,
    *,
    now: datetime,
    tz: tzinfo,
    calendar_name: str,
    late: bool = False,
    note_unknown: bool = False,
    snooze_minutes: tuple[int, ...] = DEFAULT_SNOOZE_MINUTES,
) -> dict[str, Any]:
    """Service data for ``notify.<device.notify_action>``."""
    lang = device.language if device.language in STRINGS else "en"
    s = STRINGS[lang]
    today = now.astimezone(tz).date()

    title = f"⏰ {when_phrase(reminder, now, tz, lang)}: {reminder.summary}"
    if reminder.tentative:
        title += s["tentative"]
    if late:
        title += s["late"]

    parts = [time_span(reminder, today, tz, lang)]
    if reminder.location:
        parts.append(reminder.location)
    parts.append(calendar_name)
    message = " · ".join(parts)
    if note_unknown and reminder.unknown_devices:
        names = ", ".join(f"@{name}" for name in reminder.unknown_devices)
        message += "\n" + s["unknown"].format(names=names)

    actions = [
        {
            "action": action_id(f"SNOOZE{minutes}", reminder.key, device.alias),
            "title": s["snooze"].format(d=_duration(minutes, lang)),
        }
        for minutes in snooze_minutes
    ]
    actions.append(
        {"action": action_id("DONE", reminder.key, device.alias), "title": s["done"]}
    )
    return {
        "title": title,
        "message": message,
        "data": {
            "tag": tag_for(reminder.key),
            "group": NOTIFY_GROUP,
            "channel": NOTIFY_CHANNEL_IMPORTANT
            if reminder.important
            else NOTIFY_CHANNEL,
            "importance": "high",
            "priority": "high",
            "ttl": 0,
            "clickAction": NOTIFY_CLICK_ACTION,
            "notification_icon": NOTIFY_ICON,
            "actions": actions,
        },
    }


def when_phrase(reminder: Reminder, now: datetime, tz: tzinfo, lang: str) -> str:
    """How far away the event is, as seen at ``now``."""
    s = STRINGS[lang]
    remaining = reminder.starts_at - now
    if not reminder.all_day and remaining < timedelta(hours=COUNTDOWN_HOURS):
        minutes = round(remaining.total_seconds() / 60)
        if minutes < 0:
            return s["started"]
        if minutes == 0:
            return s["now"]
        if minutes < 60:
            return s["in_min"].format(m=minutes)
        hours, rest = divmod(minutes, 60)
        if rest:
            return s["in_h_min"].format(h=hours, m=rest)
        return s["in_hour"] if hours == 1 else s["in_hours"].format(h=hours)
    days = (reminder.starts_at.astimezone(tz).date() - now.astimezone(tz).date()).days
    if days < 0:
        return s["started"]
    if days == 0:
        return s["today"]
    if days == 1:
        return s["tomorrow"]
    if days % 7 == 0:
        return s["in_week"] if days == 7 else s["in_weeks"].format(n=days // 7)
    return s["in_days"].format(n=days)


def time_span(reminder: Reminder, today: date, tz: tzinfo, lang: str) -> str:
    """'14:00–15:00', 'Tue 3 Nov 14:00–15:00', 'All day', 'Tue 3 Nov – Thu 5 Nov'."""
    s = STRINGS[lang]
    if reminder.all_day:
        assert isinstance(reminder.start, date) and isinstance(reminder.end, date)
        last = max(reminder.start, reminder.end - timedelta(days=1))  # end is exclusive
        if last != reminder.start:
            first = format_date(reminder.start, today, lang)
            return f"{first} – {format_date(last, today, lang)}"
        if reminder.start == today:
            return s["all_day"]
        return format_date(reminder.start, today, lang) + s["all_day_suffix"]
    assert isinstance(reminder.start, datetime) and isinstance(reminder.end, datetime)
    start = reminder.start.astimezone(tz)
    end = reminder.end.astimezone(tz)
    prefix = (
        "" if start.date() == today else format_date(start.date(), today, lang) + " "
    )
    if end <= start:
        return f"{prefix}{start:%H:%M}"
    ends_same_day = end.date() == start.date() or (
        end - start <= timedelta(days=1) and end.time() == datetime.min.time()
    )
    if ends_same_day:
        return f"{prefix}{start:%H:%M}–{end:%H:%M}"
    return f"{prefix}{start:%H:%M} – {format_date(end.date(), today, lang)} {end:%H:%M}"


def format_date(day: date, today: date, lang: str) -> str:
    """'Tue 3 Nov' / 'tir. 3. nov.', with the year when it isn't this year."""
    weekday = _WEEKDAYS[lang][day.weekday()]
    month = _MONTHS[lang][day.month - 1]
    text = (
        f"{weekday} {day.day} {month}"
        if lang == "en"
        else f"{weekday} {day.day}. {month}"
    )
    return text if day.year == today.year else f"{text} {day.year}"


def _duration(minutes: int, lang: str) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        return f"{minutes // 60} {STRINGS[lang]['hours_unit']}"
    return f"{minutes} min"


class Notifier:
    """Sends deliveries to devices and handles their buttons."""

    def __init__(
        self,
        hass: HomeAssistant,
        devices: Mapping[str, Device],
        *,
        fallback_device: str | None = None,
        snooze_minutes: tuple[int, ...] = DEFAULT_SNOOZE_MINUTES,
    ) -> None:
        self.hass = hass
        self.devices = dict(devices)
        self.fallback_device = fallback_device
        self.snooze_minutes = snooze_minutes
        self._engine: ReminderEngine | None = None

    async def async_send(self, delivery: Delivery) -> None:
        """Send one delivery to each of its devices (the engine's ``send``)."""
        reminder = delivery.reminder
        now = dt_util.utcnow()
        tz = dt_util.get_default_time_zone()
        state = self.hass.states.get(reminder.calendar)
        calendar_name = state.name if state else reminder.calendar
        calls = []
        failures: list[str] = []
        for alias in delivery.devices:
            if (device := self.devices.get(alias)) is None:
                failures.append(f"@{alias}: not configured")
                continue
            data = build_message(
                reminder,
                device,
                now=now,
                tz=tz,
                calendar_name=calendar_name,
                late=delivery.late,
                note_unknown=alias == self.fallback_device,
                snooze_minutes=self.snooze_minutes,
            )
            calls.append((alias, self._async_notify(device, data)))
        results = await asyncio.gather(*(c for _, c in calls), return_exceptions=True)
        failures += [
            f"@{alias}: {result}"
            for (alias, _), result in zip(calls, results, strict=True)
            if isinstance(result, BaseException)
        ]
        if failures:
            raise HomeAssistantError("; ".join(failures))

    async def async_clear(self, key: str, alias: str) -> None:
        """Remove a reminder's notification from one device."""
        if (device := self.devices.get(alias)) is None:
            return
        await self._async_notify(
            device, {"message": "clear_notification", "data": {"tag": tag_for(key)}}
        )

    async def _async_notify(self, device: Device, data: dict[str, Any]) -> None:
        await self.hass.services.async_call(
            "notify", device.notify_action.removeprefix("notify."), data, blocking=True
        )

    # --- buttons -------------------------------------------------------------

    def async_attach(self, engine: ReminderEngine) -> CALLBACK_TYPE:
        """Handle Snooze and Done for ``engine``; returns an unsubscribe."""
        self._engine = engine
        return self.hass.bus.async_listen(
            MOBILE_APP_ACTION_EVENT, self._async_on_action
        )

    async def _async_on_action(self, event: Event) -> None:
        parsed = parse_action(str(event.data.get("action", "")))
        if parsed is None or self._engine is None:
            return
        minutes, key, alias = parsed
        if minutes is not None:
            await self._engine.async_snooze(key, alias, minutes)
        else:
            await self._engine.async_done(key, alias)
        # Personal: only the tapped device loses the notification. A snooze
        # brings it back on that device with the same tag.
        try:
            await self.async_clear(key, alias)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not clear %s on @%s: %s", key, alias, err)
