"""Config flow tests: the entry, its options, and device subentries."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigSubentryData,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.calendar_reminders.const import DOMAIN, SUBENTRY_DEVICE

from .common import CAL


@pytest.fixture
def no_setup() -> Generator[AsyncMock]:
    """Create entries without starting the engine."""
    with patch(
        "custom_components.calendar_reminders.async_setup_entry", return_value=True
    ) as setup:
        yield setup


@pytest.fixture
def notify(hass: HomeAssistant) -> None:
    for name in (
        "mobile_app_annas_phone",
        "mobile_app_bens_phone",
        "persistent_notification",
    ):
        async_mock_service(hass, "notify", name)


def device(alias: str, action: str, language: str = "en") -> ConfigSubentryData:
    return ConfigSubentryData(
        data={"alias": alias, "notify_action": action, "language": language},
        subentry_type=SUBENTRY_DEVICE,
        title=f"@{alias} ({action})",
        unique_id=alias,
    )


def make_entry(
    hass: HomeAssistant, *devices: ConfigSubentryData, **options
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Calendar Reminders",
        options={
            "calendars": [CAL],
            "default_devices": [],
            "snooze_short": 10,
            "snooze_long": 60,
            **options,
        },
        subentries_data=list(devices),
    )
    entry.add_to_hass(hass)
    return entry


# --- entry --------------------------------------------------------------------


async def test_user_step_creates_entry(
    hass: HomeAssistant, no_setup: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"calendars": [CAL, "calendar.family"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Calendar Reminders"
    entry = result["result"]
    assert entry.version == 2
    assert entry.data == {}
    assert entry.options == {
        "calendars": [CAL, "calendar.family"],
        "default_devices": [],
        "snooze_short": 10,
        "snooze_long": 60,
        "all_day_time": "18:00:00",
    }
    assert no_setup.called


async def test_only_one_entry(hass: HomeAssistant, no_setup: AsyncMock) -> None:
    make_entry(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


# --- options ------------------------------------------------------------------


async def test_options_offer_devices_and_save(
    hass: HomeAssistant, no_setup: AsyncMock
) -> None:
    entry = make_entry(
        hass,
        device("anna", "mobile_app_annas_phone"),
        device("ben", "mobile_app_bens_phone", "nb"),
        default_devices=["anna", "gone"],  # "gone" was deleted: not offered back
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    defaults = {str(key): key.default() for key in schema if callable(key.default)}
    assert defaults["default_devices"] == ["anna"]
    assert defaults["all_day_time"] == "18:00:00"  # not set yet: the default
    options = next(v for k, v in schema.items() if str(k) == "default_devices")
    assert [o["value"] for o in options.config["options"]] == ["anna", "ben"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "calendars": [CAL],
            "default_devices": ["anna", "ben"],
            "fallback_device": "anna",
            "snooze_short": 5,
            "snooze_long": 30,
            "all_day_time": "07:45:00",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "calendars": [CAL],
        "default_devices": ["anna", "ben"],
        "fallback_device": "anna",
        "snooze_short": 5,
        "snooze_long": 30,
        "all_day_time": "07:45:00",
    }


async def test_options_without_fallback(
    hass: HomeAssistant, no_setup: AsyncMock
) -> None:
    entry = make_entry(
        hass, device("anna", "mobile_app_annas_phone"), fallback_device="anna"
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"calendars": [CAL], "snooze_short": 10, "snooze_long": 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "fallback_device" not in entry.options
    assert entry.options["default_devices"] == []
    assert entry.options["all_day_time"] == "18:00:00"


# --- device subentries --------------------------------------------------------


async def test_add_device(
    hass: HomeAssistant, no_setup: AsyncMock, notify: None
) -> None:
    entry = make_entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DEVICE), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    action = next(
        v for k, v in result["data_schema"].schema.items() if str(k) == "notify_action"
    )
    assert action.config["options"] == [
        "mobile_app_annas_phone",
        "mobile_app_bens_phone",
    ]

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "alias": " @ANNA ",
            "notify_action": "notify.mobile_app_annas_phone",
            "language": "en",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (sub,) = entry.subentries.values()
    assert sub.title == "@anna (mobile_app_annas_phone)"
    assert sub.unique_id == "anna"
    assert dict(sub.data) == {
        "alias": "anna",
        "notify_action": "mobile_app_annas_phone",
        "language": "en",
    }


@pytest.mark.parametrize(
    ("user_input", "errors"),
    [
        (
            {"alias": "r s", "notify_action": "mobile_app_annas_phone"},
            {"alias": "invalid_alias"},
        ),
        (
            {"alias": "ben-2", "notify_action": "mobile_app_annas_phone"},
            {"alias": "invalid_alias"},
        ),
        (
            {"alias": "anna", "notify_action": "mobile_app_annas_phone"},
            {"alias": "alias_taken"},
        ),
        (
            {"alias": "ben", "notify_action": "mobile_app_nope"},
            {"notify_action": "notify_not_found"},
        ),
        (
            {"alias": "", "notify_action": "mobile_app_nope"},
            {"alias": "invalid_alias", "notify_action": "notify_not_found"},
        ),
    ],
)
async def test_add_device_errors(
    hass: HomeAssistant,
    no_setup: AsyncMock,
    notify: None,
    user_input: dict[str, str],
    errors: dict[str, str],
) -> None:
    entry = make_entry(hass, device("anna", "mobile_app_annas_phone"))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DEVICE), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**user_input, "language": "nb"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors
    assert len(entry.subentries) == 1


async def test_edit_device(
    hass: HomeAssistant, no_setup: AsyncMock, notify: None
) -> None:
    entry = make_entry(
        hass,
        device("anna", "mobile_app_annas_phone"),
        device("ben", "mobile_app_bens_phone", "en"),
    )
    ben = next(s for s in entry.subentries.values() if s.unique_id == "ben")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_DEVICE),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": ben.subentry_id},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    # Its own alias isn't "taken"; another device's is.
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"alias": "anna", "notify_action": "mobile_app_bens_phone", "language": "nb"},
    )
    assert result["errors"] == {"alias": "alias_taken"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"alias": "ben", "notify_action": "mobile_app_bens_phone", "language": "nb"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[ben.subentry_id].data["language"] == "nb"
