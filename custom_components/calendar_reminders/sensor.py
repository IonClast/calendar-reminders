"""``sensor.calendar_reminders_next``: when the next reminder goes out."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN

if TYPE_CHECKING:
    from . import CalendarRemindersConfigEntry
    from .engine import ReminderEngine


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CalendarRemindersConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NextReminderSensor(entry.entry_id, entry.runtime_data.engine)])


class NextReminderSensor(SensorEntity):
    """Time of the next reminder (or snooze), with what it is for."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True
    _attr_translation_key = "next"
    _attr_should_poll = False

    def __init__(self, entry_id: str, engine: ReminderEngine) -> None:
        self._engine = engine
        self.entity_id = f"sensor.{DOMAIN}_next"
        self._attr_unique_id = f"{entry_id}_next"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Calendar Reminders",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._engine.async_add_listener(self._handle_change))

    @callback
    def _handle_change(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> datetime | None:
        due = self._engine.next_due()
        return due[0] if due else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        due = self._engine.next_due()
        attrs: dict[str, Any] = {"pending": self._engine.pending_count()}
        if due is None:
            return attrs
        fire_at, reminder, devices = due
        return attrs | {
            "summary": reminder.summary,
            "calendar": reminder.calendar,
            "start": reminder.start.isoformat(),
            "offset": reminder.offset.token(),
            "devices": list(devices),
            "important": reminder.important,
            "snoozed": fire_at != reminder.fire_at,
        }
