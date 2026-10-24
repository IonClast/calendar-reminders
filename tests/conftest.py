"""Shared fixtures."""

from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.calendar.const import DATA_COMPONENT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import CAL, START


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA load custom_components/ in every test."""
    return


@pytest.fixture(autouse=True)
def frontend_stub(hass: HomeAssistant) -> Generator[MagicMock]:
    """hass_frontend (a 110 MB wheel) isn't installed for tests.

    Mark frontend as loaded so our dependency on it is met, and stub the one
    frontend call we make.
    """
    hass.config.components.add("frontend")
    with patch("custom_components.calendar_reminders.add_extra_js_url") as add_js:
        yield add_js


@pytest.fixture
async def calendar(
    hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> Any:
    """A local calendar "Test" in Europe/Oslo, at START."""
    freezer.move_to(START)
    await hass.config.async_set_time_zone("Europe/Oslo")
    # local_calendar writes .storage/<name>.ics; the harness config dir has no .storage.
    hass.config.config_dir = str(tmp_path)
    (tmp_path / ".storage").mkdir()
    entry = MockConfigEntry(domain="local_calendar", data={"calendar_name": "Test"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DATA_COMPONENT].get_entity(CAL)
