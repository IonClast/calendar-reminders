"""Smoke test: the HA test harness runs and the integration's manifest loads."""

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.calendar_reminders.const import DOMAIN


async def test_integration_loads(hass: HomeAssistant) -> None:
    """HA finds the custom integration and reads its manifest."""
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.domain == DOMAIN
    assert integration.is_built_in is False
