"""Config flow for Calendar Reminders.

- The entry holds the calendars to watch and the reminder options
  (default devices, fallback device, snooze lengths).
- Each phone or tablet is a "device" subentry: its alias (as in "@anna"), its
  legacy notify action and the language of its notifications. HA's own
  integration page adds, edits and deletes them.
"""

from __future__ import annotations

import re
from typing import Any

import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)

from .const import (
    CONF_ALIAS,
    CONF_ALL_DAY_TIME,
    CONF_CALENDARS,
    CONF_DEFAULT_DEVICES,
    CONF_FALLBACK_DEVICE,
    CONF_LANGUAGE,
    CONF_NOTIFY_ACTION,
    CONF_SNOOZE_LONG,
    CONF_SNOOZE_SHORT,
    DEFAULT_ALL_DAY_TIME,
    DEFAULT_SNOOZE_MINUTES,
    DOMAIN,
    SUBENTRY_DEVICE,
)

_ALIAS_RE = re.compile(r"^[a-z0-9_]+$")
_LANGUAGE_OPTIONS = [
    SelectOptionDict(value="en", label="English"),
    SelectOptionDict(value="nb", label="Norsk bokmål"),
]


def device_subentries(entry: ConfigEntry) -> dict[str, ConfigSubentry]:
    """The entry's device subentries by alias."""
    return {
        sub.data[CONF_ALIAS]: sub
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_DEVICE
    }


def _calendars_selector() -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain="calendar", multiple=True))


def _snooze_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=1,
            max=1440,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="min",
        )
    )


class CalendarRemindersConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the single Calendar Reminders entry."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the calendars to watch. Devices are added afterwards."""
        if user_input is not None:
            short, long = DEFAULT_SNOOZE_MINUTES
            return self.async_create_entry(
                title="Calendar Reminders",
                data={},
                options={
                    CONF_CALENDARS: user_input[CONF_CALENDARS],
                    CONF_DEFAULT_DEVICES: [],
                    CONF_SNOOZE_SHORT: short,
                    CONF_SNOOZE_LONG: long,
                    CONF_ALL_DAY_TIME: DEFAULT_ALL_DAY_TIME,
                },
            )
        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {probatio.Required(CONF_CALENDARS): _calendars_selector()}
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CalendarRemindersOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_DEVICE: DeviceSubentryFlow}


class CalendarRemindersOptionsFlow(OptionsFlow):
    """Calendars, default and fallback devices, snooze lengths."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        aliases = sorted(device_subentries(self.config_entry))
        if user_input is not None:
            options = {
                CONF_CALENDARS: user_input[CONF_CALENDARS],
                CONF_DEFAULT_DEVICES: user_input.get(CONF_DEFAULT_DEVICES, []),
                CONF_SNOOZE_SHORT: int(user_input[CONF_SNOOZE_SHORT]),
                CONF_SNOOZE_LONG: int(user_input[CONF_SNOOZE_LONG]),
                CONF_ALL_DAY_TIME: user_input[CONF_ALL_DAY_TIME],
            }
            if fallback := user_input.get(CONF_FALLBACK_DEVICE):
                options[CONF_FALLBACK_DEVICE] = fallback
            return self.async_create_entry(data=options)

        current = self.config_entry.options
        device_options = [SelectOptionDict(value=a, label=f"@{a}") for a in aliases]
        schema: dict[Any, Any] = {
            probatio.Required(
                CONF_CALENDARS, default=current.get(CONF_CALENDARS, [])
            ): _calendars_selector(),
            probatio.Optional(
                CONF_DEFAULT_DEVICES,
                default=[
                    a for a in current.get(CONF_DEFAULT_DEVICES, []) if a in aliases
                ],
            ): SelectSelector(
                SelectSelectorConfig(
                    options=device_options, multiple=True, mode=SelectSelectorMode.LIST
                )
            ),
            probatio.Optional(
                CONF_FALLBACK_DEVICE,
                description={"suggested_value": current.get(CONF_FALLBACK_DEVICE)},
            ): SelectSelector(
                SelectSelectorConfig(
                    options=device_options, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            probatio.Required(
                CONF_SNOOZE_SHORT,
                default=current.get(CONF_SNOOZE_SHORT, DEFAULT_SNOOZE_MINUTES[0]),
            ): _snooze_selector(),
            probatio.Required(
                CONF_SNOOZE_LONG,
                default=current.get(CONF_SNOOZE_LONG, DEFAULT_SNOOZE_MINUTES[1]),
            ): _snooze_selector(),
            probatio.Required(
                CONF_ALL_DAY_TIME,
                default=current.get(CONF_ALL_DAY_TIME, DEFAULT_ALL_DAY_TIME),
            ): TimeSelector(),
        }
        return self.async_show_form(step_id="init", data_schema=probatio.Schema(schema))


class DeviceSubentryFlow(ConfigSubentryFlow):
    """Add or edit a device: alias, notify action, language."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = _validate_device(self.hass, self._get_entry(), user_input)
            if not errors:
                return self.async_create_entry(
                    title=_title(data), data=data, unique_id=data[CONF_ALIAS]
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _device_schema(self.hass), user_input or {CONF_LANGUAGE: "en"}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = _validate_device(
                self.hass, self._get_entry(), user_input, editing=subentry.subentry_id
            )
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=_title(data),
                    data=data,
                    unique_id=data[CONF_ALIAS],
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _device_schema(self.hass), user_input or dict(subentry.data)
            ),
            errors=errors,
        )


def _device_schema(hass: HomeAssistant) -> probatio.Schema:
    notify = sorted(hass.services.async_services_for_domain("notify"))
    mobile = [n for n in notify if n.startswith("mobile_app_")]
    return probatio.Schema(
        {
            probatio.Required(CONF_ALIAS): TextSelector(),
            probatio.Required(CONF_NOTIFY_ACTION): SelectSelector(
                SelectSelectorConfig(
                    options=mobile, custom_value=True, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            probatio.Required(CONF_LANGUAGE): SelectSelector(
                SelectSelectorConfig(
                    options=_LANGUAGE_OPTIONS, mode=SelectSelectorMode.LIST
                )
            ),
        }
    )


def _validate_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    user_input: dict[str, Any],
    *,
    editing: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    alias = str(user_input[CONF_ALIAS]).strip().lstrip("@").lower()
    action = str(user_input[CONF_NOTIFY_ACTION]).strip().removeprefix("notify.")
    data = {
        CONF_ALIAS: alias,
        CONF_NOTIFY_ACTION: action,
        CONF_LANGUAGE: user_input[CONF_LANGUAGE],
    }
    errors: dict[str, str] = {}
    taken = device_subentries(entry)
    if not _ALIAS_RE.match(alias):
        errors[CONF_ALIAS] = "invalid_alias"
    elif alias in taken and taken[alias].subentry_id != editing:
        errors[CONF_ALIAS] = "alias_taken"
    if not hass.services.has_service("notify", action):
        errors[CONF_NOTIFY_ACTION] = "notify_not_found"
    return data, errors


def _title(data: dict[str, Any]) -> str:
    return f"@{data[CONF_ALIAS]} ({data[CONF_NOTIFY_ACTION]})"
