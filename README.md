<p align="center">
  <img src="https://raw.githubusercontent.com/IonClast/calendar-reminders/main/icons/icon%402x.png" width="140" alt="Calendar Reminders icon"/>
</p>

# Calendar Reminders for Home Assistant

Native-feeling **push reminders for calendar events** via the Home Assistant
Companion app — no automations, no YAML, no blueprints.

Home Assistant can trigger automations from calendars, but it has no built-in
"remind me 10 minutes before" like Google Calendar or Outlook. This
integration fills that gap until it lands in core.

## Features

- **Appointment form card** (`custom:calendar-reminder-card`): create events
  with the same fields as HA's built-in dialog — calendar, title, all-day,
  start/end, location, description — **plus a reminder picker** ("10 min
  before", "1 hour before", custom minutes, or "1 day before" for all-day
  events). The card is bundled with the integration and auto-registered;
  just add it to any dashboard, no manual resource setup.
- Works with **every** calendar integration (Local Calendar, Google, CalDAV,
  MS365, Remote Calendar, Waste Collection Schedule, ...) because it only
  consumes the standard `calendar` entity.
- Multiple reminder offsets per event (e.g. 10 min **and** 1 hour before).
- All-day event handling: remind at a chosen time of day, N days before
  (perfect for bin collection the evening before).
- **Per-event overrides** via a tag in the event description:
  - `#remind 30m` → single reminder 30 minutes before
  - `#remind 5m 2h` → two reminders
  - `#remind 1d` → for all-day events: remind 1 day before
- **Snooze button** on every notification (10 min), on iOS and Android.
- Restart-safe: fired reminders are persisted, and reminders missed during a
  short restart (up to 10 min) are still delivered.
- Fully UI-configured, with an options flow to change everything later.
- Fires a `calendar_reminders_reminder_fired` event on the HA bus so you can
  hook extra automations (TTS announcements, lights, etc.).

## Installation (HACS custom repository)

1. HACS → three-dot menu → **Custom repositories**
2. Add this repository URL, category **Integration**
3. Install **Calendar Reminders**, restart Home Assistant
4. Settings → Devices & Services → **Add Integration** → Calendar Reminders

## Configuration

| Field | Meaning |
|---|---|
| Calendars to watch | Any `calendar.*` entities |
| Notify targets | Your `notify.mobile_app_*` services (multi-select) |
| Offsets | Minutes before timed events (pick presets or type your own) |
| All-day time | Time of day to send all-day reminders |
| All-day days before | 1 = the day before at that time, 0 = same day |

You can create **multiple instances** — e.g. family calendar → both phones,
work calendar → only yours.

## The appointment card

Add it to any dashboard: **Edit dashboard → Add card → Custom: Calendar
Reminder Card**, or in YAML:

```yaml
type: custom:calendar-reminder-card
title: New appointment          # optional
calendars:                      # optional, defaults to all calendars
  - calendar.family
  - calendar.personal
```

Fill in the appointment exactly like the built-in dialog, tick the reminder
chips you want (multiple allowed, plus a custom minutes field), and hit
*Create appointment*. Under the hood the card calls
`calendar.create_event` and stores the reminder as a `#remind` tag in the
event description — the backend engine watches for it and sends the push at
the right time. That also means reminders work on events you create
*anywhere else* (Google Calendar app, phone, etc.): just type e.g.
`#remind 30m` in the event description.

Note: event creation requires a **writable** calendar (Local Calendar,
Google with write access, CalDAV). Read-only calendars like Remote Calendar
will show an error.

## Known limitations

- Home Assistant's calendar API does not expose the reminder settings stored
  *inside* the source calendar (Google reminders, ICS `VALARM`). Defaults +
  the `#remind` tag are used instead.
- Events are fetched every 15 minutes with a 48 h lookahead, so an event
  created less than ~15 min before its start may be missed (same limitation
  as HA calendar triggers).
- Timing resolution is 1 minute.

## Roadmap ideas

- Read `VALARM` blocks directly from ICS-based calendars
- Configurable snooze durations
- Quiet hours
- A `sensor` showing the next scheduled reminder

PRs welcome. If Home Assistant ships this natively — even better, that's the
goal. Vote for it on the [official feature requests](https://github.com/OpenHomeFoundation/roadmap).
