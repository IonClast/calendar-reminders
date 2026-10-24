"""Parse and write the ``#remind`` line (version 2) in an event description.

Format (see the README)::

    #remind <when>... [@device]... [!]
    when    0 | <n>m | <n>h | <n>d | <n>w | <n>d@HH:MM | <n>   (bare number = minutes)
    #remind off

- It is the last non-blank line of the description; case does not matter.
- Minutes and hours are absolute durations. Days and weeks keep the event's
  wall-clock time across DST changes. ``<n>d@HH:MM`` fires n days before the
  event's date at HH:MM local time (meant for all-day events).
- Unknown tokens are ignored and collected in ``RemindLine.unknown``.

Pure module: no Home Assistant imports, so it is unit-tested without a hass.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from enum import StrEnum

TAG = "#remind"

_TAG_RE = re.compile(r"^\s*#remind\b(.*)$", re.IGNORECASE)
_OFFSET_RE = re.compile(r"^(\d{1,4})([mhdw]?)$")
_AT_RE = re.compile(r"^(\d{1,2})d@(\d{1,2}):(\d{2})$")
_ALIAS_RE = re.compile(r"^@([a-z0-9_]+)$")
# Google Calendar stores descriptions edited on the web as HTML.
_HTML_BREAK_RE = re.compile(r"<br\s*/?>|</p\s*>|</div\s*>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class Unit(StrEnum):
    """How an offset is measured."""

    MINUTES = "m"  # absolute duration (hours are stored as minutes)
    DAYS = "d"  # calendar days, same wall-clock time (weeks are stored as days)
    DAYS_AT = "d@"  # calendar days before the event's date, at a fixed local time


@dataclass(frozen=True, slots=True)
class Offset:
    """One reminder time relative to the event start."""

    unit: Unit
    amount: int  # minutes for MINUTES, days for DAYS and DAYS_AT
    at: time | None = None  # only for DAYS_AT

    def token(self) -> str:
        """Canonical token: the largest unit that divides evenly."""
        if self.unit is Unit.DAYS_AT:
            assert self.at is not None
            return f"{self.amount}d@{self.at:%H:%M}"
        if self.unit is Unit.DAYS:
            if self.amount and self.amount % 7 == 0:
                return f"{self.amount // 7}w"
            return f"{self.amount}d"
        if self.amount == 0:
            return "0"
        if self.amount % 60 == 0:
            return f"{self.amount // 60}h"
        return f"{self.amount}m"

    def trigger_time(self, start: datetime | date, tz: tzinfo) -> datetime:
        """When this offset fires for an event starting at ``start``.

        ``start`` is an aware datetime for timed events or a date for all-day
        events (which start at local midnight). The result is aware, in ``tz``,
        and always a real instant (times in a DST gap are moved forward).
        """
        local = _local_start(start, tz)
        if self.unit is Unit.MINUTES:
            fire = local.astimezone(UTC) - timedelta(minutes=self.amount)
        elif self.unit is Unit.DAYS:
            fire = _localize(
                local.replace(tzinfo=None) - timedelta(days=self.amount), tz
            )
        else:
            assert self.at is not None
            day = local.date() - timedelta(days=self.amount)
            fire = _localize(datetime.combine(day, self.at), tz)
        return fire.astimezone(tz)

    def sort_key(self) -> tuple[int, int, int]:
        """Earliest-looking first: days before minutes, larger before smaller."""
        if self.unit is Unit.MINUTES:
            return (1, -self.amount, 0)
        at_minutes = self.at.hour * 60 + self.at.minute if self.at else 0
        # Same day count: a fixed-time reminder sorts by its time of day.
        return (0, -self.amount, at_minutes)


@dataclass(frozen=True, slots=True)
class RemindLine:
    """A parsed ``#remind`` line."""

    offsets: tuple[Offset, ...] = ()
    devices: tuple[str, ...] = ()  # lower-case aliases without "@", in order
    important: bool = False
    off: bool = False
    unknown: tuple[str, ...] = field(default=(), compare=False)

    @property
    def active(self) -> bool:
        """True if this line should produce reminders."""
        return not self.off and bool(self.offsets)

    def serialize(self) -> str:
        """Canonical text of the line, e.g. ``#remind 1d 1h @anna @ben !``."""
        if self.off:
            return f"{TAG} off"
        parts = [TAG]
        parts += [o.token() for o in sorted(self.offsets, key=Offset.sort_key)]
        parts += [f"@{d}" for d in self.devices]
        if self.important:
            parts.append("!")
        return " ".join(parts)


def parse(
    description: str | None, aliases: Iterable[str] | None = None
) -> RemindLine | None:
    """Parse the ``#remind`` line of a description, or return None if it has none.

    If ``aliases`` is given, ``@names`` not in it are reported as unknown
    instead of being returned as devices.
    """
    found = _find_line(description)
    if found is None:
        return None
    known = {a.lower() for a in aliases} if aliases is not None else None

    tokens = found.lower().replace("!", " ! ").split()
    if tokens and tokens[0] == "off":
        return RemindLine(off=True, unknown=tuple(tokens[1:]))

    offsets: dict[Offset, None] = {}
    devices: dict[str, None] = {}
    important = False
    unknown: list[str] = []
    for tok in tokens:
        if tok == "!":
            important = True
        elif (offset := _parse_offset(tok)) is not None:
            offsets[offset] = None
        elif (m := _ALIAS_RE.match(tok)) and (known is None or m[1] in known):
            devices[m[1]] = None
        else:
            unknown.append(tok)
    return RemindLine(
        offsets=tuple(offsets),
        devices=tuple(devices),
        important=important,
        unknown=tuple(unknown),
    )


def split(description: str | None) -> tuple[str, str | None]:
    """Split a plain-text description into (body, remind line text or None)."""
    lines = (description or "").splitlines()
    idx = _last_nonblank(lines)
    if idx is None or not _TAG_RE.match(lines[idx]):
        return (description or "").rstrip(), None
    body = "\n".join(lines[:idx]).rstrip()
    return body, lines[idx].strip()


def apply(description: str | None, line: RemindLine | None) -> str:
    """Return ``description`` with its ``#remind`` line replaced, added or removed.

    ``line=None`` removes it. The rest of the description is kept as is.
    Plain-text descriptions only (local calendars); HA can't edit Google events.
    """
    body, _ = split(description)
    if line is None:
        return body
    return f"{body}\n{line.serialize()}" if body else line.serialize()


def _find_line(description: str | None) -> str | None:
    """Return the text after ``#remind`` on the last non-blank line, if any."""
    if not description:
        return None
    text = description
    if "<" in text:
        text = _HTML_TAG_RE.sub("", _HTML_BREAK_RE.sub("\n", text))
    text = html.unescape(text).replace("\xa0", " ")
    lines = text.splitlines()
    idx = _last_nonblank(lines)
    if idx is None:
        return None
    m = _TAG_RE.match(lines[idx])
    return m[1] if m else None


def _last_nonblank(lines: list[str]) -> int | None:
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            return i
    return None


def _parse_offset(tok: str) -> Offset | None:
    if m := _AT_RE.match(tok):
        hour, minute = int(m[2]), int(m[3])
        if hour > 23 or minute > 59:
            return None
        return Offset(Unit.DAYS_AT, int(m[1]), time(hour, minute))
    if m := _OFFSET_RE.match(tok):
        n, unit = int(m[1]), m[2]
        if unit == "h":
            return Offset(Unit.MINUTES, n * 60)
        if unit == "d":
            return Offset(Unit.DAYS, n)
        if unit == "w":
            return Offset(Unit.DAYS, n * 7)
        return Offset(Unit.MINUTES, n)  # "m" or a bare number (0.2.0)
    return None


def _local_start(start: datetime | date, tz: tzinfo) -> datetime:
    if isinstance(start, datetime):
        if start.tzinfo is None:
            raise ValueError("timed event start must be timezone-aware")
        return start.astimezone(tz)
    return _localize(datetime.combine(start, time()), tz)


def _localize(naive: datetime, tz: tzinfo) -> datetime:
    """Attach ``tz`` to a wall-clock time as a real instant.

    With fold=0 (PEP 495) a time in the spring-forward gap resolves forward
    (02:30 -> 03:30 CEST) and a repeated autumn time resolves to its first pass.
    """
    return naive.replace(tzinfo=tz).astimezone(UTC).astimezone(tz)
