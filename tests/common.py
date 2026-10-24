"""Helpers shared by the tests: Oslo time, a frozen clock, a local calendar."""

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

OSLO = ZoneInfo("Europe/Oslo")
CAL = "calendar.test"
START = datetime(2026, 11, 2, 8, 0, tzinfo=OSLO)  # a Monday, CET


def oslo(*args: int) -> datetime:
    return datetime(*args, tzinfo=OSLO)


async def advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: datetime
) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


async def settle(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let the calendar's 1 s push debounce run."""
    await advance(hass, freezer, dt_util.utcnow() + timedelta(seconds=2))


async def add_event(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    entity: Any,
    summary: str,
    start: datetime | date,
    description: str | None = None,
    **extra: Any,
) -> None:
    end = start + (
        timedelta(days=1) if not isinstance(start, datetime) else timedelta(hours=1)
    )
    event = {"dtstart": start, "dtend": end, "summary": summary, **extra}
    if description is not None:
        event["description"] = description
    await entity.async_create_event(**event)
    await settle(hass, freezer)


async def find_uid(hass: HomeAssistant, entity: Any, summary: str) -> str:
    events = await entity.async_get_events(hass, START, START + timedelta(days=40))
    return next(e.uid for e in events if e.summary == summary)
