"""Constants for the Calendar Reminders integration."""

DOMAIN = "calendar_reminders"

# Config keys
CONF_CALENDARS = "calendars"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_OFFSETS = "offsets_minutes"
CONF_ALL_DAY_TIME = "all_day_time"
CONF_ALL_DAY_DAYS_BEFORE = "all_day_days_before"

# Defaults
DEFAULT_OFFSETS = ["10", "60"]
DEFAULT_ALL_DAY_TIME = "18:00:00"
DEFAULT_ALL_DAY_DAYS_BEFORE = 1
OFFSET_PRESETS = ["5", "10", "15", "30", "60", "120", "240"]

# Timing
REFRESH_INTERVAL_MIN = 15   # how often we re-fetch upcoming events
TICK_INTERVAL_SEC = 60      # how often we check if a reminder is due
LOOKAHEAD_HOURS = 48        # how far ahead we fetch events
GRACE_MINUTES = 10          # fire reminders up to this late (e.g. after restart)
SNOOZE_MINUTES = 10

# Notification action / events
ACTION_PREFIX = "CALREM_SNOOZE_"
MOBILE_APP_ACTION_EVENT = "mobile_app_notification_action"
BUS_EVENT_FIRED = f"{DOMAIN}_reminder_fired"

# Storage
STORAGE_VERSION = 1

# Description tag, e.g. "#remind 30m 2h" or "#remind 1d"
REMIND_TAG_RE = r"#remind\s+((?:\d+\s*[mhd]?\s*)+)"
