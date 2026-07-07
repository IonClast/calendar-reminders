"""Config flow for Calendar Reminders."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)

from .const import (
    CONF_ALL_DAY_DAYS_BEFORE,
    CONF_ALL_DAY_TIME,
    CONF_CALENDARS,
    CONF_NOTIFY_SERVICES,
    CONF_OFFSETS,
    DEFAULT_ALL_DAY_DAYS_BEFORE,
    DEFAULT_ALL_DAY_TIME,
    DEFAULT_OFFSETS,
    DOMAIN,
    OFFSET_PRESETS,
)


def _notify_service_options(hass: HomeAssistant) -> list[str]:
    """All registered notify services, mobile apps first."""
    services = sorted(hass.services.async_services().get("notify", {}))
    mobile = [s for s in services if s.startswith("mobile_app_")]
    rest = [s for s in services if not s.startswith("mobile_app_")]
    return mobile + rest


def _validate_offsets(raw: list[str]) -> bool:
    parsed = []
    for item in raw:
        try:
            n = int(str(item).strip())
        except ValueError:
            return False
        if n <= 0:
            return False
        parsed.append(n)
    return bool(parsed)


def _build_schema(hass: HomeAssistant, defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_CALENDARS, default=defaults.get(CONF_CALENDARS, [])
            ): EntitySelector(
                EntitySelectorConfig(domain="calendar", multiple=True)
            ),
            vol.Required(
                CONF_NOTIFY_SERVICES,
                default=defaults.get(CONF_NOTIFY_SERVICES, []),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=_notify_service_options(hass),
                    multiple=True,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_OFFSETS,
                default=defaults.get(CONF_OFFSETS, DEFAULT_OFFSETS),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=OFFSET_PRESETS,
                    multiple=True,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_ALL_DAY_TIME,
                default=defaults.get(CONF_ALL_DAY_TIME, DEFAULT_ALL_DAY_TIME),
            ): TimeSelector(),
            vol.Required(
                CONF_ALL_DAY_DAYS_BEFORE,
                default=defaults.get(
                    CONF_ALL_DAY_DAYS_BEFORE, DEFAULT_ALL_DAY_DAYS_BEFORE
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=7, step=1, mode=NumberSelectorMode.BOX
                )
            ),
        }
    )


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    user_input[CONF_ALL_DAY_DAYS_BEFORE] = int(
        user_input[CONF_ALL_DAY_DAYS_BEFORE]
    )
    return user_input


class CalendarRemindersConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _validate_offsets(user_input[CONF_OFFSETS]):
                errors["base"] = "invalid_offsets"
            else:
                return self.async_create_entry(
                    title="Calendar Reminders",
                    data=_normalize(user_input),
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(self.hass, user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CalendarRemindersOptionsFlow()


class CalendarRemindersOptionsFlow(OptionsFlow):
    """Allow changing everything after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _validate_offsets(user_input[CONF_OFFSETS]):
                errors["base"] = "invalid_offsets"
            else:
                return self.async_create_entry(
                    title="", data=_normalize(user_input)
                )
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(self.hass, current),
            errors=errors,
        )
