"""Reminder engine for calendar_reminders.

- Reads events from the configured calendar entities: a push subscription
  (``CalendarEntity.async_subscribe_events``), a rescan every 15 minutes and at
  start, and the ``calendar.get_events`` action if the entity API is missing.
- Turns every event with an active ``#remind`` line into one ``Reminder`` per
  offset. The key is calendar + UID + recurrence_id + start + offset, so a
  rename keeps the key and a move makes a new one. Events without a UID use
  the title instead.
- One timer for the next due time; reminders fire to the second.
- A reminder whose time passed (HA was down, or the line was added late) is
  sent at once marked late, unless the event has started; then it is missed.
- Fired reminders and snoozes are kept in ``.storage``, so a restart neither
  repeats nor loses them.

Sending is injected (``send``), so the notifier and the tests plug in here.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from functools import partial
from typing import Any

from homeassistant.components.calendar.const import DATA_COMPONENT, CalendarEventStatus
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    BUS_EVENT_FIRED,
    DUE_TOLERANCE_SECONDS,
    ENGINE_STORAGE_KEY,
    ENGINE_STORAGE_VERSION,
    LATE_AFTER_SECONDS,
    PRUNE_AFTER_DAYS,
    RESCAN_MINUTES,
    RESUBSCRIBE_AT,
    WINDOW_FUTURE,
    WINDOW_PAST,
)
from .remind_line import Offset, Unit, parse

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """What the engine watches and who gets reminders by default."""

    calendars: tuple[str, ...]  # calendar entity IDs
    aliases: tuple[
        str, ...
    ]  # configured device aliases, e.g. ("anna", "ben", "kitchen")
    default_devices: tuple[str, ...]  # for a line without any @device
    fallback_device: str | None = None  # also gets reminders naming an unknown @device
    # Time of day for a plain "1d"/"1w" on an all-day event; None = local midnight.
    all_day_time: time | None = None


@dataclass(frozen=True, slots=True)
class CalendarItem:
    """One event occurrence, normalized from ``CalendarEvent.as_dict()``."""

    calendar: str
    summary: str
    start: datetime | date
    end: datetime | date
    description: str | None = None
    location: str | None = None
    uid: str | None = None
    recurrence_id: str | None = None
    tentative: bool = False

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)

    @property
    def identity(self) -> str:
        """What makes this occurrence the same event across renames."""
        if self.uid:
            return f"uid:{self.uid}:{self.recurrence_id or ''}"
        return (
            f"title:{self.summary}"  # e.g. some waste-collection calendars have no UID
        )


@dataclass(frozen=True, slots=True)
class Reminder:
    """One reminder instance: an occurrence x an offset."""

    key: str
    calendar: str
    summary: str
    location: str | None
    start: datetime | date
    end: datetime | date
    all_day: bool
    tentative: bool
    offset: Offset
    fire_at: datetime  # UTC
    starts_at: datetime  # UTC; all-day events start at local midnight
    devices: tuple[str, ...]
    important: bool
    unknown_devices: tuple[str, ...] = ()  # @names not configured (typos), without "@"


@dataclass(frozen=True, slots=True)
class Delivery:
    """A reminder to send now."""

    reminder: Reminder
    devices: tuple[str, ...]
    late: bool
    snoozed: bool


type SendCallback = Callable[[Delivery], Awaitable[None]]


def parse_event(calendar: str, data: dict[str, Any], tz: tzinfo) -> CalendarItem | None:
    """Normalize an event dict (push, rescan or action); None if unusable."""
    start = _to_date_or_datetime(data.get("start"), tz)
    end = _to_date_or_datetime(data.get("end"), tz)
    if start is None or end is None:
        return None
    return CalendarItem(
        calendar=calendar,
        summary=data.get("summary") or "",
        start=start,
        end=end,
        description=data.get("description"),
        location=data.get("location"),
        uid=data.get("uid"),
        recurrence_id=data.get("recurrence_id"),
        tentative=data.get("status") == CalendarEventStatus.TENTATIVE,
    )


def reminder_key(item: CalendarItem, offset: Offset) -> str:
    """Stable key: calendar + identity + start + offset."""
    if isinstance(item.start, datetime):
        start = item.start.astimezone(UTC).isoformat()
    else:
        start = item.start.isoformat()
    raw = "|".join((item.calendar, item.identity, start, offset.token()))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def reminders_for_event(
    item: CalendarItem, config: EngineConfig, tz: tzinfo
) -> tuple[list[Reminder], tuple[str, ...]]:
    """The reminders an event gets, plus unknown tokens from its line.

    A line without @devices goes to the default devices. A line naming an
    unknown @device (a typo) goes to the devices it names correctly plus the
    fallback device, so the typo gets noticed and fixed.

    On an all-day event, a plain day or week offset fires at the configured
    all-day time: "1d" becomes "1d@18:00". An explicit "1d@07:30" is kept.
    """
    line = parse(item.description, aliases=config.aliases)
    if line is None:
        return [], ()
    unknown_devices = tuple(
        t[1:] for t in line.unknown if t.startswith("@") and len(t) > 1
    )
    if not line.devices and not unknown_devices:
        devices = config.default_devices
    elif unknown_devices and config.fallback_device not in (None, *line.devices):
        devices = (*line.devices, config.fallback_device)
    else:
        devices = line.devices
    if not line.active or not devices:
        return [], line.unknown
    if isinstance(item.start, datetime):
        starts_at = item.start.astimezone(UTC)
    else:
        starts_at = datetime.combine(item.start, time.min, tzinfo=tz).astimezone(UTC)
    # Effective offsets, de-duplicated: with an all-day time of 18:00, "1d" and
    # "1d@18:00" on the same all-day event are one reminder.
    offsets = dict.fromkeys(_effective(o, item, config) for o in line.offsets)
    reminders = [
        Reminder(
            key=reminder_key(item, offset),
            calendar=item.calendar,
            summary=item.summary,
            location=item.location,
            start=item.start,
            end=item.end,
            all_day=item.all_day,
            tentative=item.tentative,
            offset=offset,
            fire_at=offset.trigger_time(item.start, tz).astimezone(UTC),
            starts_at=starts_at,
            devices=devices,
            important=line.important,
            unknown_devices=unknown_devices,
        )
        for offset in offsets
    ]
    return reminders, line.unknown


def _effective(offset: Offset, item: CalendarItem, config: EngineConfig) -> Offset:
    if item.all_day and offset.unit is Unit.DAYS and config.all_day_time is not None:
        return Offset(Unit.DAYS_AT, offset.amount, config.all_day_time)
    return offset


class ReminderEngine:
    """Watches calendars, schedules reminders and hands them to ``send``."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: EngineConfig,
        send: SendCallback,
        *,
        storage_key: str = ENGINE_STORAGE_KEY,
    ) -> None:
        self.hass = hass
        self.config = config
        self._send = send
        self._store: Store[dict[str, Any]] = Store(
            hass, ENGINE_STORAGE_VERSION, storage_key
        )
        self._items: dict[str, list[CalendarItem]] = {}
        self._reminders: dict[str, Reminder] = {}
        # key -> {"at": iso, "start": iso[, "missed": True]}
        self._fired: dict[str, dict[str, Any]] = {}
        # key -> {device: until iso}
        self._snoozes: dict[str, dict[str, str]] = {}
        self._unknown: list[dict[str, Any]] = []
        self._unavailable: set[str] = set()
        self._send_errors = 0
        self._subscriptions: dict[str, CALLBACK_TYPE] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._timer: CALLBACK_TYPE | None = None
        self._listeners: list[CALLBACK_TYPE] = []
        self._lock = asyncio.Lock()

    # --- lifecycle -----------------------------------------------------------

    async def async_start(self) -> None:
        """Load state and start watching once HA has started."""
        data = await self._store.async_load() or {}
        self._fired = data.get("fired", {})
        self._snoozes = data.get("snoozes", {})
        hour, minute = RESUBSCRIBE_AT
        self._unsubs += [
            async_track_time_interval(
                self.hass, self._async_rescan_tick, timedelta(minutes=RESCAN_MINUTES)
            ),
            async_track_time_change(
                self.hass, self._async_resubscribe, hour=hour, minute=minute, second=0
            ),
            async_at_started(self.hass, self._async_resubscribe),
        ]

    async def async_stop(self) -> None:
        """Stop all timers and subscriptions."""
        for unsub in (*self._unsubs, *self._subscriptions.values()):
            unsub()
        self._unsubs.clear()
        self._subscriptions.clear()
        if self._timer:
            self._timer()
            self._timer = None

    # --- reading calendars ---------------------------------------------------

    async def _async_resubscribe(self, _arg: Any = None) -> None:
        """Subscribe with a fresh window (daily and at start), then rescan."""
        for unsub in self._subscriptions.values():
            unsub()
        self._subscriptions.clear()
        await self.async_rescan()

    async def _async_rescan_tick(self, _now: datetime) -> None:
        await self.async_rescan()

    async def async_rescan(self) -> None:
        """Re-read every calendar; subscribe to any that isn't yet."""
        start, end = self._window()
        tz = dt_util.get_default_time_zone()
        for calendar in self.config.calendars:
            if calendar not in self._subscriptions:
                self._subscribe(calendar, start, end)
            try:
                raw = await self._async_fetch(calendar, start, end)
            except HomeAssistantError as err:
                _LOGGER.warning("Could not read %s: %s", calendar, err)
                raw = None
            if raw is None:
                self._unavailable.add(calendar)  # keep the last known events
                continue
            self._unavailable.discard(calendar)
            self._items[calendar] = _parse_all(calendar, raw, tz)
        self._rebuild()

    def _window(self) -> tuple[datetime, datetime]:
        now = dt_util.now()
        return now - timedelta(days=WINDOW_PAST), now + timedelta(days=WINDOW_FUTURE)

    def _entity(self, calendar: str) -> Any:
        component = self.hass.data.get(DATA_COMPONENT)
        return component.get_entity(calendar) if component else None

    def _subscribe(self, calendar: str, start: datetime, end: datetime) -> None:
        entity = self._entity(calendar)
        subscribe = getattr(entity, "async_subscribe_events", None)
        if subscribe is None:
            return  # not loaded yet, or the API is gone: the rescan covers it
        self._subscriptions[calendar] = subscribe(
            start, end, partial(self._on_push, calendar)
        )

    @callback
    def _on_push(self, calendar: str, events: list[Any] | None) -> None:
        """A calendar changed. Its window is fixed until the daily resubscribe."""
        if events is None:
            return  # the entity failed to read; keep what we have
        tz = dt_util.get_default_time_zone()
        self._items[calendar] = _parse_all(calendar, events, tz)
        self._rebuild()

    async def _async_fetch(
        self, calendar: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]] | None:
        """Events in the window as dicts, or None if the calendar isn't loaded."""
        if DATA_COMPONENT not in self.hass.data:
            return await self._async_fetch_via_action(calendar, start, end)
        entity = self._entity(calendar)
        if entity is None:
            return None
        get_events = getattr(entity, "async_get_events", None)
        if get_events is None:
            return await self._async_fetch_via_action(calendar, start, end)
        return [event.as_dict() for event in await get_events(self.hass, start, end)]

    async def _async_fetch_via_action(
        self, calendar: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Public fallback. It returns no UID, so events are keyed by title."""
        response = await self.hass.services.async_call(
            "calendar",
            "get_events",
            {"entity_id": calendar, "start_date_time": start, "end_date_time": end},
            blocking=True,
            return_response=True,
        )
        return list((response or {}).get(calendar, {}).get("events", []))

    # --- scheduling ----------------------------------------------------------

    @callback
    def _rebuild(self) -> None:
        """Recompute all reminder instances, then fire or schedule them."""
        tz = dt_util.get_default_time_zone()
        reminders: dict[str, Reminder] = {}
        unknown: list[dict[str, Any]] = []
        for calendar in self.config.calendars:
            for item in self._items.get(calendar, ()):
                found, tokens = reminders_for_event(item, self.config, tz)
                if tokens:
                    unknown.append(
                        {
                            "calendar": calendar,
                            "event": _short_hash(item.identity),
                            "tokens": tokens,
                        }
                    )
                reminders.update((r.key, r) for r in found)
        self._reminders = reminders
        self._unknown = unknown
        self.hass.async_create_task(self._async_process(), "calendar_reminders process")

    async def _async_timer_fired(self, _now: datetime) -> None:
        self._timer = None
        await self._async_process()

    async def _async_process(self) -> None:
        """Send everything due, record it, and set the timer for the next one."""
        async with self._lock:
            now = dt_util.utcnow()
            due_by = now + timedelta(seconds=DUE_TOLERANCE_SECONDS)
            late_after = timedelta(seconds=LATE_AFTER_SECONDS)
            deliveries: list[Delivery] = []
            changed = False

            for reminder in sorted(self._reminders.values(), key=lambda r: r.fire_at):
                if reminder.fire_at > due_by:
                    break
                if reminder.key in self._fired:
                    continue
                late = now - reminder.fire_at > late_after
                record: dict[str, Any] = {
                    "at": now.isoformat(),
                    "start": reminder.starts_at.isoformat(),
                }
                if late and now >= reminder.starts_at:
                    record["missed"] = True
                    _LOGGER.debug("Missed %s: the event had started", reminder.key)
                else:
                    deliveries.append(
                        Delivery(reminder, reminder.devices, late, snoozed=False)
                    )
                self._fired[reminder.key] = record
                changed = True

            for key, per_device in list(self._snoozes.items()):
                for device, until_iso in list(per_device.items()):
                    until = _utc(until_iso)
                    if until > due_by:
                        continue
                    del per_device[device]
                    changed = True
                    if (reminder := self._reminders.get(key)) is not None:
                        late = now - until > late_after
                        deliveries.append(
                            Delivery(reminder, (device,), late, snoozed=True)
                        )
                if not per_device:
                    del self._snoozes[key]

            changed |= self._prune(now)
            if changed:
                await self._async_save()
            self._schedule_next(now)

        for delivery in deliveries:
            await self._async_deliver(delivery)
        self._notify_listeners()

    def _prune(self, now: datetime) -> bool:
        cutoff = now - timedelta(days=PRUNE_AFTER_DAYS)
        old = [k for k, rec in self._fired.items() if _utc(rec["start"]) < cutoff]
        for key in old:
            del self._fired[key]
        return bool(old)

    @callback
    def _schedule_next(self, now: datetime) -> None:
        if self._timer:
            self._timer()
            self._timer = None
        if (upcoming := self._next_time(now)) is not None:
            self._timer = async_track_point_in_utc_time(
                self.hass, self._async_timer_fired, upcoming
            )

    def _next_time(self, now: datetime) -> datetime | None:
        times = [
            r.fire_at
            for r in self._reminders.values()
            if r.key not in self._fired and r.fire_at > now
        ]
        times += [_utc(u) for per in self._snoozes.values() for u in per.values()]
        return min(times, default=None)

    async def _async_deliver(self, delivery: Delivery) -> None:
        reminder = delivery.reminder
        try:
            await self._send(delivery)
        except Exception:
            self._send_errors += 1
            _LOGGER.exception("Sending reminder %s failed", reminder.key)
        self.hass.bus.async_fire(
            BUS_EVENT_FIRED,
            {
                "key": reminder.key,
                "calendar": reminder.calendar,
                "summary": reminder.summary,
                "start": reminder.start.isoformat(),
                "offset": reminder.offset.token(),
                "devices": list(delivery.devices),
                "important": reminder.important,
                "unknown_devices": list(reminder.unknown_devices),
                "late": delivery.late,
                "snoozed": delivery.snoozed,
            },
        )

    async def _async_save(self) -> None:
        await self._store.async_save({"fired": self._fired, "snoozes": self._snoozes})

    # --- buttons -------------------------------------------------------------

    async def async_snooze(self, key: str, device: str, minutes: int) -> bool:
        """Fire ``key`` again on ``device`` only, ``minutes`` from now."""
        if key not in self._reminders:
            return False
        async with self._lock:
            now = dt_util.utcnow()
            until = now + timedelta(minutes=minutes)
            self._snoozes.setdefault(key, {})[device] = until.isoformat()
            await self._async_save()
            self._schedule_next(now)
        self._notify_listeners()
        return True

    async def async_done(self, key: str, device: str) -> bool:
        """``device`` is done with ``key``: drop its snooze, if any."""
        async with self._lock:
            per_device = self._snoozes.get(key, {})
            if per_device.pop(device, None) is not None:
                if not per_device:
                    del self._snoozes[key]
                await self._async_save()
                self._schedule_next(dt_util.utcnow())
        self._notify_listeners()
        return key in self._reminders

    # --- read side -----------------------------------------------------------

    @property
    def reminders(self) -> dict[str, Reminder]:
        """All current reminder instances by key."""
        return self._reminders

    def next_due(self) -> tuple[datetime, Reminder, tuple[str, ...]] | None:
        """The next time something will be sent, what, and to which devices."""
        now = dt_util.utcnow()
        upcoming = [
            (r.fire_at, r, r.devices)
            for r in self._reminders.values()
            if r.key not in self._fired and r.fire_at > now
        ]
        upcoming += [
            (_utc(until), self._reminders[key], (device,))
            for key, per in self._snoozes.items()
            if key in self._reminders
            for device, until in per.items()
        ]
        return min(upcoming, key=lambda item: item[0], default=None)

    def pending_count(self) -> int:
        """Reminders still to be sent for the first time."""
        now = dt_util.utcnow()
        return sum(
            1
            for r in self._reminders.values()
            if r.key not in self._fired and r.fire_at > now
        )

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call ``listener`` after every change; returns an unsubscribe."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    def diagnostics(self) -> dict[str, Any]:
        """State for diagnostics. No event titles, descriptions or places."""
        return {
            "calendars": {
                cal: {
                    "events": len(self._items.get(cal, ())),
                    "subscribed": cal in self._subscriptions,
                    "unavailable": cal in self._unavailable,
                }
                for cal in self.config.calendars
            },
            "reminders": len(self._reminders),
            "pending": self.pending_count(),
            "fired": sum(1 for rec in self._fired.values() if not rec.get("missed")),
            "missed": sum(1 for rec in self._fired.values() if rec.get("missed")),
            "snoozes": sum(len(per) for per in self._snoozes.values()),
            "unknown_tokens": self._unknown,
            "send_errors": self._send_errors,
        }


def _parse_all(calendar: str, events: Iterable[Any], tz: tzinfo) -> list[CalendarItem]:
    items = (parse_event(calendar, e, tz) for e in events if isinstance(e, dict))
    return [item for item in items if item is not None]


def _to_date_or_datetime(value: Any, tz: tzinfo) -> datetime | date | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=tz)
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    if "T" in value:
        parsed = dt_util.parse_datetime(value)
        if parsed is None:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)
    return dt_util.parse_date(value)


def _utc(iso: str) -> datetime:
    parsed = datetime.fromisoformat(iso)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]
