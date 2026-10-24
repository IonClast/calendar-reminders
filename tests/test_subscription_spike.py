"""Phase 0 S3, in-process part: an integration can subscribe to a local calendar.

Runs against the real local_calendar platform inside the HA test harness. It checks
that the path the engine uses (component -> entity -> async_subscribe_events)
works and pushes promptly after a save. Timing on real hardware is measured separately.
"""

import asyncio
import time
from datetime import timedelta
from pathlib import Path

from homeassistant.components.calendar.const import DATA_COMPONENT
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

ENTITY_ID = "calendar.s3_test"


async def test_subscription_pushes_after_save(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """A create in a local calendar reaches an in-process subscriber in < 2 s."""
    # local_calendar writes .storage/<name>.ics; the harness config dir has no .storage.
    hass.config.config_dir = str(tmp_path)
    (tmp_path / ".storage").mkdir()
    entry = MockConfigEntry(domain="local_calendar", data={"calendar_name": "S3 test"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity = hass.data[DATA_COMPONENT].get_entity(ENTITY_ID)
    assert entity is not None

    now = dt_util.now()
    pushes: asyncio.Queue[tuple[float, list | None]] = asyncio.Queue()
    unsub = entity.async_subscribe_events(
        now,
        now + timedelta(days=35),
        lambda events: pushes.put_nowait((time.perf_counter(), events)),
    )
    try:
        start = now + timedelta(days=3)
        t0 = time.perf_counter()
        await entity.async_create_event(
            dtstart=start, dtend=start + timedelta(minutes=15), summary="S3 push"
        )
        t_push, events = await asyncio.wait_for(pushes.get(), 2)
        assert events is not None
        assert [e["summary"] for e in events] == ["S3 push"]
        print(f"S3 in-process push latency: {(t_push - t0) * 1000:.1f} ms")
        assert t_push - t0 < 2
    finally:
        unsub()
