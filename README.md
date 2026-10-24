<p align="center">
  <img src="https://raw.githubusercontent.com/IonClast/calendar-reminders/main/custom_components/calendar_reminders/brand/icon%402x.png" width="140" alt="Calendar Reminders icon"/>
</p>

# Calendar Reminders for Home Assistant

**Per-event push reminders for Home Assistant calendars**, sent to the phones
you choose through the Companion app, with *Snooze* and *Done* buttons. No
automations, no YAML.

Home Assistant can trigger automations from calendars, but it has no "remind me
1 hour before" like Google Calendar or Outlook. With this integration you write
one line at the end of the event's description:

```
#remind 1d 1h @anna @ben
```

and Anna's and Ben's phones get a reminder a day before and an hour before.

> **Status:** 0.3.0 is a test version, installable from `main` through HACS.
> It replaces 0.2.0, which worked differently (see *Upgrading from 0.2.0*).

## Features

- **Reminders set on the event itself**, in a `#remind` line. It works in any
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
- Android channel: *Calendar reminders* (important ones use the alarm stream).

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

## Where to write the line

- **Home Assistant's own Add/Edit event dialog**, in the description. A
  Reminders section inside that dialog is planned for a later version.
- **Any calendar app** that edits the description, for example the Google
  Calendar app.
- The bundled `custom:calendar-reminder-card` (from 0.2.0) still works and
  writes lines this version understands. It will be rebuilt in a later version.

## Known limitations

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
```

CI runs hassfest, HACS validation, ruff and pytest on every push.
