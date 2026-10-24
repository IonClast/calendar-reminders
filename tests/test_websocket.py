"""WebSocket API used by the dialog's Reminders section and the card."""

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.calendar_reminders.const import DOMAIN

from .common import CAL
from .test_setup import setup, standard_entry


def mobile_app(hass: HomeAssistant, device_name: str, user_id: str) -> None:
    MockConfigEntry(
        domain="mobile_app", data={"device_name": device_name, "user_id": user_id}
    ).add_to_hass(hass)


async def test_config_lists_devices_and_marks_own(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
) -> None:
    # The admin user (who the WebSocket client logs in as) owns Anna's phone.
    mobile_app(hass, "Annas Phone", hass_admin_user.id)
    mobile_app(hass, "Bens Phone", "someone-else")
    entry = standard_entry(hass, all_day_time="19:30:00")
    await setup(hass, entry)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/config"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] == {
        "loaded": True,
        "devices": [
            {"alias": "anna", "name": "Annas Phone", "language": "en", "own": True},
            {"alias": "ben", "name": "Bens Phone", "language": "nb", "own": False},
        ],
        "default_devices": ["anna", "ben"],
        "fallback_device": "anna",
        "all_day_time": "19:30",
        "calendars": [CAL],
    }


async def test_device_without_app_uses_alias(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    entry = standard_entry(hass)
    await setup(hass, entry)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/config"})
    devices = (await client.receive_json())["result"]["devices"]
    assert devices == [
        {"alias": "anna", "name": "anna", "language": "en", "own": False},
        {"alias": "ben", "name": "ben", "language": "nb", "own": False},
    ]


async def test_config_when_not_loaded(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/config"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] == {"loaded": False}
