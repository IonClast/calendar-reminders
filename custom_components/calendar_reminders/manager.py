"""Reminder engine for Calendar Reminders.

Design:
- Every REFRESH_INTERVAL_MIN we call calendar.get_events for the next
  LOOKAHEAD_HOURS on the configured calendars and rebuild the pending
  reminder list.
- Every TICK_INTERVAL_SEC we check whether any pending reminder is due
  and send it via the configured notify services (companion app push).
- Fired reminders are persisted with a Store so a restart does not
  re-send them. Reminders missed by up to GRACE_MINUTES (e.g. HA was
  restarting) are still delivered.
- Notifications carry a "Snooze" action button; the companion app fires
  mobile_app_notification_action, which we listen for to reschedule.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_PREFIX,
    BUS_EVENT_FIRED,
    CONF_ALL_DAY_DAYS_BEFORE,
    CONF_ALL_DAY_TIME,
    CONF_CALENDARS,
    CONF_NOTIFY_SERVICES,
    CONF_OFFSETS,
    DEFAULT_ALL_DAY_DAYS_BEFORE,
    DEFAULT_ALL_DAY_TIME,
    DEFAULT_OFFSETS,
    DOMAIN,
    GRACE_MINUTES,
    LOOKAHEAD_HOURS,
    MOBILE_APP_ACTION_EVENT,
    REFRESH_INTERVAL_MIN,
    REMIND_TAG_RE,
    SNOOZE_MINUTES,
    STORAGE_VERSION,
    TICK_INTERVAL_SEC,
)

_LOGGER = logging.getLogger(__name__)

_TAG_RE = re.compile(REMIND_TAG_RE, re.IGNORECASE)
_TOKEN_RE = re.compile(r"(\d+)\s*([mhd]?)", re.IGNORECASE)


@dataclass
class Reminder:
    """A single scheduled reminder for one event at one offset."""

    key: str
    fire_at: datetime
    summary: str
    calendar: str
    start_text: str
    is_all_day: bool
    location: str | None = None
    offset_label: str = ""
    snoozed: bool = field(default=False)


def _offset_label(minutes: int) -> str:
    """Human label for an offset, e.g. 90 -> '1 h 30 min'."""
    if minutes % 1440 == 0:
        d = minutes // 1440
        return f"{d} day{'s' if d != 1 else ''}"
    hours, mins = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} h")
    if mins:
        parts.append(f"{mins} min")
    return " ".join(parts) or "0 min"


def _parse_offset_tokens(raw: str) -> list[int]:
    """Parse '30m 2h 1d' (bare number = minutes) into minutes list."""
    minutes: list[int] = []
    for value, unit in _TOKEN_RE.findall(raw):
        n = int(value)
        unit = unit.lower()
        if unit == "h":
            n *= 60
        elif unit == "d":
            n *= 1440
        if n > 0:
            minutes.append(n)
    return sorted(set(minutes))


class ReminderManager:
    """Owns the refresh/tick loops and notification dispatch."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._fired: dict[str, str] = {}          # key -> fired iso timestamp
        self._pending: dict[str, Reminder] = {}   # rebuilt on every refresh
        self._snoozed: dict[str, Reminder] = {}   # survives refresh rebuilds
        self._action_map: dict[str, Reminder] = {}  # notif action id -> reminder
        self._unsubs: list = []

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------
    @property
    def _conf(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def _calendars(self) -> list[str]:
        return self._conf.get(CONF_CALENDARS, [])

    @property
    def _notify_services(self) -> list[str]:
        return [
            s.removeprefix("notify.")
            for s in self._conf.get(CONF_NOTIFY_SERVICES, [])
        ]

    @property
    def _default_offsets(self) -> list[int]:
        raw = self._conf.get(CONF_OFFSETS, DEFAULT_OFFSETS)
        out = []
        for item in raw:
            try:
                n = int(str(item).strip())
                if n > 0:
                    out.append(n)
            except ValueError:
                continue
        return sorted(set(out)) or [10]

    @property
    def _all_day_time(self) -> time:
        parsed = dt_util.parse_time(
            self._conf.get(CONF_ALL_DAY_TIME, DEFAULT_ALL_DAY_TIME)
        )
        return parsed or time(18, 0)

    @property
    def _all_day_days_before(self) -> int:
        return int(
            self._conf.get(CONF_ALL_DAY_DAYS_BEFORE, DEFAULT_ALL_DAY_DAYS_BEFORE)
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def async_start(self) -> None:
        stored = await self._store.async_load()
        if stored:
            self._fired = stored.get("fired", {})
        await self._async_refresh()
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._async_refresh,
                timedelta(minutes=REFRESH_INTERVAL_MIN),
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._async_tick,
                timedelta(seconds=TICK_INTERVAL_SEC),
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                MOBILE_APP_ACTION_EVENT, self._handle_mobile_action
            )
        )
        _LOGGER.debug(
            "Started: calendars=%s notify=%s offsets=%s",
            self._calendars,
            self._notify_services,
            self._default_offsets,
        )

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # ------------------------------------------------------------------
    # Refresh: fetch events and rebuild pending reminders
    # ------------------------------------------------------------------
    async def _async_refresh(self, _now: datetime | None = None) -> None:
        if not self._calendars:
            return
        now = dt_util.now()
        try:
            response = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "entity_id": self._calendars,
                    "start_date_time": now.isoformat(),
                    "end_date_time": (
                        now + timedelta(hours=LOOKAHEAD_HOURS)
                    ).isoformat(),
                },
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Fetching calendar events failed: %s", err)
            return

        pending: dict[str, Reminder] = {}
        for cal_id, payload in (response or {}).items():
            for event in payload.get("events", []):
                for reminder in self._reminders_for_event(cal_id, event, now):
                    pending[reminder.key] = reminder
        self._pending = pending
        self._prune_fired(now)
        _LOGGER.debug("Refresh complete: %d pending reminders", len(pending))

    def _reminders_for_event(
        self, cal_id: str, event: dict[str, Any], now: datetime
    ) -> list[Reminder]:
        summary = event.get("summary") or "(no title)"
        start_raw = str(event.get("start", ""))
        description = event.get("description") or ""
        location = event.get("location")
        out: list[Reminder] = []

        tag_offsets: list[int] | None = None
        if match := _TAG_RE.search(description):
            parsed = _parse_offset_tokens(match.group(1))
            if parsed:
                tag_offsets = parsed

        if "T" in start_raw:
            start_dt = dt_util.parse_datetime(start_raw)
            if start_dt is None:
                return out
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            start_text = dt_util.as_local(start_dt).strftime("%a %H:%M")
            for offset in tag_offsets or self._default_offsets:
                fire_at = start_dt - timedelta(minutes=offset)
                if fire_at < now - timedelta(minutes=GRACE_MINUTES):
                    continue
                key = self._make_key(cal_id, summary, start_raw, offset)
                out.append(
                    Reminder(
                        key=key,
                        fire_at=fire_at,
                        summary=summary,
                        calendar=cal_id,
                        start_text=start_text,
                        is_all_day=False,
                        location=location,
                        offset_label=_offset_label(offset),
                    )
                )
        else:
            start_date = dt_util.parse_date(start_raw)
            if start_date is None:
                return out
            days_before_options = [self._all_day_days_before]
            if tag_offsets:
                day_tokens = [o // 1440 for o in tag_offsets if o % 1440 == 0]
                if day_tokens:
                    days_before_options = day_tokens
            for days_before in days_before_options:
                fire_day: date = start_date - timedelta(days=days_before)
                naive = datetime.combine(fire_day, self._all_day_time)
                fire_at = naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                if fire_at < now - timedelta(minutes=GRACE_MINUTES):
                    continue
                key = self._make_key(
                    cal_id, summary, start_raw, days_before * 1440
                )
                when = (
                    "today"
                    if days_before == 0
                    else "tomorrow"
                    if days_before == 1
                    else f"in {days_before} days"
                )
                out.append(
                    Reminder(
                        key=key,
                        fire_at=fire_at,
                        summary=summary,
                        calendar=cal_id,
                        start_text=when,
                        is_all_day=True,
                        location=location,
                        offset_label=when,
                    )
                )
        return out

    @staticmethod
    def _make_key(cal_id: str, summary: str, start_raw: str, offset: int) -> str:
        raw = f"{cal_id}|{summary}|{start_raw}|{offset}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def _prune_fired(self, now: datetime) -> None:
        cutoff = now - timedelta(days=3)
        for key, iso in list(self._fired.items()):
            fired_at = dt_util.parse_datetime(iso)
            if fired_at is None or fired_at < cutoff:
                self._fired.pop(key, None)

    # ------------------------------------------------------------------
    # Tick: fire due reminders
    # ------------------------------------------------------------------
    async def _async_tick(self, _now: datetime | None = None) -> None:
        now = dt_util.now()
        grace = timedelta(minutes=GRACE_MINUTES)
        due = [
            r
            for r in list(self._pending.values()) + list(self._snoozed.values())
            if r.key not in self._fired and r.fire_at <= now <= r.fire_at + grace
        ]
        for reminder in due:
            await self._async_send(reminder)
            self._fired[reminder.key] = now.isoformat()
            self._snoozed.pop(reminder.key, None)
        if due:
            self._store.async_delay_save(lambda: {"fired": self._fired}, 10)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    async def _async_send(self, reminder: Reminder) -> None:
        action_id = f"{ACTION_PREFIX}{reminder.key}"
        self._action_map[action_id] = reminder

        if reminder.is_all_day:
            title = f"📅 {reminder.start_text.capitalize()}: {reminder.summary}"
            message = f"All-day event {reminder.start_text}"
        else:
            prefix = "⏰ Snoozed: " if reminder.snoozed else f"⏰ In {reminder.offset_label}: "
            title = f"{prefix}{reminder.summary}"
            message = f"Starts {reminder.start_text}"
        if reminder.location:
            message += f" — {reminder.location}"

        payload = {
            "title": title,
            "message": message,
            "data": {
                "tag": reminder.key,
                "actions": [
                    {
                        "action": action_id,
                        "title": f"Snooze {SNOOZE_MINUTES} min",
                    }
                ],
            },
        }
        for service in self._notify_services:
            try:
                await self.hass.services.async_call(
                    "notify", service, payload, blocking=True
                )
            except HomeAssistantError as err:
                _LOGGER.warning("notify.%s failed: %s", service, err)

        self.hass.bus.async_fire(
            BUS_EVENT_FIRED,
            {
                "summary": reminder.summary,
                "calendar": reminder.calendar,
                "start": reminder.start_text,
                "offset": reminder.offset_label,
            },
        )
        _LOGGER.debug("Sent reminder %s (%s)", reminder.summary, reminder.key)

    # ------------------------------------------------------------------
    # Snooze handling
    # ------------------------------------------------------------------
    @callback
    def _handle_mobile_action(self, event: Event) -> None:
        action = event.data.get("action", "")
        if not action.startswith(ACTION_PREFIX):
            return
        original = self._action_map.get(action)
        if original is None:
            return
        now = dt_util.now()
        snooze_key = f"{original.key}s{int(now.timestamp())}"
        self._snoozed[snooze_key] = Reminder(
            key=snooze_key,
            fire_at=now + timedelta(minutes=SNOOZE_MINUTES),
            summary=original.summary,
            calendar=original.calendar,
            start_text=original.start_text,
            is_all_day=original.is_all_day,
            location=original.location,
            offset_label=original.offset_label,
            snoozed=True,
        )
        _LOGGER.debug("Snoozed '%s' for %d min", original.summary, SNOOZE_MINUTES)
