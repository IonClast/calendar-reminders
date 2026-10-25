<p align="center">
  <img src="https://raw.githubusercontent.com/IonClast/calendar-reminders/main/custom_components/calendar_reminders/brand/icon%402x.png" width="140" alt="Calendar Reminders icon"/>
</p>

# Calendar Reminders for Home Assistant

**Per-event push reminders for Home Assistant calendars**, sent to the phones
you choose through the Companion app, with *Snooze* and *Done* buttons. No
automations, no YAML.

Home Assistant can trigger automations from calendars, but it has no "remind me
1 hour before" like Google Calendar or Outlook. This integration adds a
**Reminders** section to Home Assistant's own *Add / Edit event* dialog: tap
*1 hour* and *1 day*, tap Anna and Ben, save. Their phones get a reminder a day
before and an hour before.

Behind the scenes the section stores one line at the end of the description,
`#remind 1d 1h @anna @ben`, so any calendar app can read and write it too.

> **Status:** 0.5.0 is a test version, installable from `main` through HACS.
> It replaces 0.2.0, which worked differently (see *Upgrading from 0.2.0*).

## Features

- **Set reminders in Home Assistant's own event dialog** (Calendar panel,
  calendar card, Companion app), or in the bundled card for wall panels.
- **Reminders stored on the event itself**, in a `#remind` line. It works in any
  calendar app that can edit the description, including the Google Calendar app.
- **Recipients per event**: name devices with `@alias`. A line without `@` goes
  to your default devices.
- **Snooze and Done buttons.** Snooze brings the reminder back on that phone
  only; Done clears it on that phone only.
- **Important reminders** (`!`) use Android's alarm stream, so they ring even
  on silent.
- **Texts in English or Norwegian (bokmål)**, set per device.
- **Accurate timing**: reminders fire to the second. Changes in local
  calendars are picked up at once; other calendars within 15 minutes.
  Reminders can be up to 4 weeks before the event.
- **Restart-safe**: a reminder is never sent twice. One that was due while Home
  Assistant was down is sent at once, marked late, unless the event has started.
- `sensor.calendar_reminders_next` and a `calendar_reminders_reminder_fired`
  event for your own automations.
- Works with every calendar integration (Local Calendar, Google, CalDAV, ...)
  because it only uses the standard calendar entity.

## Requirements

- Home Assistant **2026.10** or newer.
- The Home Assistant Companion app on each phone or tablet. The notifications
  are built for **Android**; iOS is untested.

## Installation (HACS custom repository)

1. HACS → three-dot menu → **Custom repositories**.
2. Add this repository's URL, category **Integration**.
3. Install **Calendar Reminders** and restart Home Assistant.

## Setup

The order matters, because the options list the devices you have added.

1. **Settings → Devices & services → Add integration → Calendar Reminders.**
   Pick the calendars to watch.
2. **Add your devices.** On the integration's page, choose *Add device* for each
   phone or tablet:

   | Field | Example | Meaning |
   |---|---|---|
   | Alias | `anna` | The name used in the line: `@anna`. Lowercase letters, digits and `_`. |
   | Notify action | `mobile_app_annas_phone` | The device's Companion app notify action. |
   | Language | English / Norsk bokmål | Language of the texts and buttons on this device. |

3. **Configure** the integration:

   | Option | Meaning |
   |---|---|
   | Default devices | Get the reminder when the line names no `@device`. |
   | Fallback device | Also gets the reminder when the line names an unknown `@device` (a typo), with a note saying which, so you can fix it. |
   | Short / long snooze | Minutes for the two snooze buttons (default 10 and 60). |
   | All-day reminder time | When `1d`, `2d`, `1w` ... on an all-day event fire (default 18:00). |

## Adding reminders

### In Home Assistant's event dialog

Open **Calendar → Add event** (or tap an event to edit it). The same dialog
opens from the calendar card on any dashboard and in the Companion app. Below
the description there is a **Reminders** section:

- **When:** tap one or more times: *At start*, *10 min*, *30 min*, *1 hour*,
  *2 hours*, *1 day before*. For all-day events: *Day before*, *2 days before*,
  *Week before* (at the all-day reminder time) and *Same day at 07:00*.
  *Other* adds any duration, for example 45 minutes or 3 weeks before.
  *At a time* picks a clock time: the same day, the day before, 2 or 3 days or
  a week before, at for example 07:30.
- **Who:** tap the devices that should get it. Your own phone is preselected.
- **Ring even on silent** for important reminders.

Save the event as usual. Opening an existing event shows its reminders, and
untapping all times removes them. The section writes the `#remind` line into the
description; you never have to type it.

### The card (wall panels, dashboards)

```yaml
type: custom:calendar-reminder-card
title: New appointment      # optional
calendars:                  # optional; default: the calendars the integration watches
  - calendar.family
```

It creates events (title, calendar, all day, start, end, location, description,
repeat) with the same Reminders section, and lists the coming events: *Edit*
opens one in the card. For a repeating event, the change applies to that
occurrence only; edit the whole series in Home Assistant's own dialog.

### In other calendar apps

Write the line yourself as the last line of the description, for example in the
Google Calendar app. See below.

## The `#remind` line

It must be the **last line** of the event's description. Case doesn't matter.

```
#remind <when>... [@device]... [!]
#remind off
```

| Token | Meaning |
|---|---|
| `0` | At the start |
| `15m`, `90m` | Minutes before (an exact duration) |
| `2h` | Hours before (an exact duration) |
| `1d`, `3d` | Days before, at the same clock time (all-day events: at the all-day reminder time) |
| `1w`, `2w` | Weeks before, likewise |
| `1d@07:30`, `0d@07:30` | *n* days before the event's date, at that time |
| `15` | A plain number means minutes (as in 0.2.0) |
| `@anna` | Send to this device (repeat for more) |
| `!` | Important: ring even on silent (also `30m!`) |
| `off` | No reminders for this event |

Examples:

- `#remind 1h` → 1 hour before, to the default devices.
- `#remind 1d 1h @anna @ben` → a day before and an hour before, to Anna and Ben.
- `#remind 30m!` → 30 minutes before, ringing even on silent.
- `#remind 1d @kitchen` → for an all-day event (say, bin day): the evening
  before, at the all-day reminder time.
- `#remind 1d 0d@07:30 @kitchen` → the evening before and the morning of.

Details:

- Minutes and hours are exact durations. Days and weeks keep the clock time
  across daylight-saving changes: `1d` before 10:00 is 10:00 the day before.
- On an all-day event, `1d`, `2d`, `1w` ... fire at the all-day reminder time
  (default 18:00); `1d@07:30` picks its own time. Minutes and hours count from
  the event's start at midnight: `2h` is 22:00 the evening before.
- Words the line doesn't understand are ignored and listed in the diagnostics.
- Renaming an event doesn't send its reminder again. Moving it schedules the
  reminder for the new time.
- Recurring events get a reminder for each occurrence.

## Notifications

On an English device:

> **⏰ In 1 hour: Dentist**
> 10:00–11:00 · Main Street Clinic · Family calendar
> *Snooze 10 min · Snooze 1 h · Done*

On a Norwegian device: **⏰ Om 1 time: Dentist**, with *Slumre 10 min · Slumre 1 t · Ferdig*.

- The text counts down from the moment it's sent, so a snoozed or late
  reminder says how far away the event really is. Late reminders are marked
  "(late)", tentative events "(tentative)".
- Tapping the notification opens the Home Assistant calendar.
- Android channel: *Calendar reminders* (important ones use the alarm stream),
  created with vibration on.
- No vibration in vibrate mode? Android keeps the settings a channel was
  created with, and versions before 0.5.0 created it without vibration. On the
  phone: *Settings → Apps → Home Assistant → Notifications → Calendar reminders*
  → turn on vibration. Or remove the channel once from Home Assistant (the next
  reminder creates it again, with vibration): action `notify.mobile_app_<phone>`,
  message `remove_channel`, data `channel: Calendar reminders`.
- A smartwatch shows a reminder only if its phone app forwards notifications
  from the Home Assistant app (check the watch app's notification settings and
  its sleep or do-not-disturb mode).

## Sensor and event

`sensor.calendar_reminders_next` shows when the next reminder goes out
(a timestamp), with the attributes `summary`, `calendar`, `start`, `offset`,
`devices`, `important`, `snoozed` and `pending`.

Every reminder sent fires `calendar_reminders_reminder_fired`:

```yaml
triggers:
  - trigger: event
    event_type: calendar_reminders_reminder_fired
    event_data:
      important: true
actions:
  - action: tts.speak
    # ...
```

Event data: `key`, `calendar`, `summary`, `start`, `offset`, `devices`,
`important`, `late`, `snoozed`, `unknown_devices`.

## Known limitations

- The Reminders section hooks into Home Assistant's own dialog. A frontend update
  can change that dialog; then the section doesn't show, the dialog itself keeps
  working, and the card still works.
- The card's date and time fields can't tell apart the two passes of the hour
  that repeats when clocks go back. It refuses to save an event that starts and
  ends inside that hour; use Home Assistant's own dialog for it.

- Home Assistant can create and delete Google Calendar events but not edit
  them. To change the line on an existing Google event, edit it in Google
  Calendar.
- The line is visible to everyone who can see the event, including in shared
  Google calendars.
- A reminder is sent at most once. If sending fails (for example, a removed
  phone), it is counted in the diagnostics and not retried.
- Reminders stored inside the source calendar (Google reminders, ICS `VALARM`)
  aren't read; Home Assistant's calendar API doesn't expose them.

## Diagnostics

The integration's diagnostics show the configuration, per-calendar counts,
pending and missed reminders, unknown tokens and send errors. They contain no
event titles, descriptions or locations.

## Upgrading from 0.2.0

0.2.0 settings can't be carried over. Delete the old integration entry, then
set it up again as described above. Existing lines such as `#remind 30m 2h 1d`
keep working; on all-day events, `1d` fires at the all-day reminder time, as
in 0.2.0. Calendar-wide default offsets no longer exist: an event gets
reminders only when it has a `#remind` line.

## Development

Home Assistant's test harness needs Linux (it imports `fcntl`), so run the tests
in CI or under WSL:

```bash
pip install -r requirements_test.txt
pytest
ruff check . && ruff format --check .
node --test "tests/js/*.test.mjs"
```

The frontend is plain ES modules in `custom_components/calendar_reminders/www/`
(no build step): `remind-line.js` (the line, a port of `remind_line.py`; a test
checks both write the same text), `reminders-section.js`, `dialog-ext.js` and
`calendar-reminder-card.js`.

CI runs hassfest, HACS validation, ruff and pytest on every push.
