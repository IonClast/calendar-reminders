"""Constants for the Calendar Reminders integration."""

DOMAIN = "calendar_reminders"

# Config entry (options) and device subentries
CONF_CALENDARS = "calendars"
CONF_DEFAULT_DEVICES = "default_devices"  # for a #remind line without @devices
CONF_FALLBACK_DEVICE = "fallback_device"  # also gets lines naming an unknown @device
CONF_SNOOZE_SHORT = "snooze_short"
CONF_SNOOZE_LONG = "snooze_long"
CONF_ALL_DAY_TIME = "all_day_time"  # plain "1d" on an all-day event fires at this time
SUBENTRY_DEVICE = "device"
CONF_ALIAS = "alias"
CONF_NOTIFY_ACTION = "notify_action"
CONF_LANGUAGE = "language"
LANGUAGES = ("en", "nb")

# Events
MOBILE_APP_ACTION_EVENT = "mobile_app_notification_action"
BUS_EVENT_FIRED = f"{DOMAIN}_reminder_fired"

# Engine (engine.py)
ENGINE_STORAGE_KEY = f"{DOMAIN}.engine"
ENGINE_STORAGE_VERSION = 1
WINDOW_PAST = 1  # days kept behind now (snoozes after the start, late handling)
WINDOW_FUTURE = 35  # days ahead, so offsets of up to 4 weeks fire
RESCAN_MINUTES = 15  # safety net next to the subscription push
RESUBSCRIBE_AT = (0, 5)  # local HH, MM: the subscription window rolls daily
LATE_AFTER_SECONDS = 60  # sent more than this after its time = "late"
DUE_TOLERANCE_SECONDS = 1  # a timer firing this early still counts as due
PRUNE_AFTER_DAYS = 2  # forget fired/snoozed state this long after the event

# Notifier (notifier.py)
# Android channel; its importance is fixed on first use.
NOTIFY_CHANNEL = "Calendar reminders"
NOTIFY_CHANNEL_IMPORTANT = "alarm_stream"  # rings even on silent
NOTIFY_GROUP = "calendar-reminders"
NOTIFY_TAG_PREFIX = "calrem-"
NOTIFY_CLICK_ACTION = "/calendar"
NOTIFY_ICON = "mdi:calendar-clock"
DEFAULT_SNOOZE_MINUTES = (10, 60)
DEFAULT_ALL_DAY_TIME = "18:00:00"  # as 0.2.0
COUNTDOWN_HOURS = 12  # closer than this: "In 40 min"; further: "Tomorrow", "In 3 days"
