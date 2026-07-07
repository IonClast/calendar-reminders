/* Calendar Reminder Card
 *
 * A dashboard card that creates calendar appointments with the same
 * fields as Home Assistant's built-in dialog (calendar, title, all-day,
 * start, end, location, description) PLUS a reminder picker.
 *
 * Reminders are stored as a `#remind ...` tag appended to the event
 * description; the calendar_reminders backend integration parses that
 * tag and sends the push notifications at the right time.
 */

const TIMED_PRESETS = [
  { min: 5, label: "5 min before" },
  { min: 10, label: "10 min before" },
  { min: 30, label: "30 min before" },
  { min: 60, label: "1 hour before" },
  { min: 120, label: "2 hours before" },
  { min: 1440, label: "1 day before" },
];

const ALLDAY_PRESETS = [
  { min: 1440, label: "1 day before" },
  { min: 2880, label: "2 days before" },
  { min: 4320, label: "3 days before" },
];

function fmtToken(minutes) {
  if (minutes % 1440 === 0) return `${minutes / 1440}d`;
  if (minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

function pad(n) {
  return String(n).padStart(2, "0");
}

function nextHourLocal(offsetMin = 0) {
  const d = new Date(Date.now() + offsetMin * 60000);
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

function toServiceDateTime(localValue) {
  // "2026-07-08T19:00" -> "2026-07-08 19:00:00"
  return localValue.replace("T", " ") + ":00";
}

function addDays(dateStr, days) {
  const d = new Date(dateStr + "T12:00:00");
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

class CalendarReminderCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
  }

  getCardSize() {
    return 8;
  }

  _calendarEntities() {
    const all = Object.keys(this._hass.states).filter((e) =>
      e.startsWith("calendar.")
    );
    const configured = this._config.calendars;
    return configured && configured.length
      ? all.filter((e) => configured.includes(e))
      : all;
  }

  _render() {
    const calendars = this._calendarEntities();
    const calOptions = calendars
      .map((e) => {
        const name = this._hass.states[e].attributes.friendly_name || e;
        return `<option value="${e}">${name}</option>`;
      })
      .join("");

    const presetHtml = (presets, cls) =>
      presets
        .map(
          (p) => `
        <label class="chip ${cls}">
          <input type="checkbox" value="${p.min}" ${
            p.min === 10 && cls === "timed" ? "checked" : ""
          }/>
          <span>${p.label}</span>
        </label>`
        )
        .join("");

    this.innerHTML = `
      <ha-card header="${this._config.title || "New appointment"}">
        <div class="crc">
          <label>Calendar
            <select id="crc-cal">${calOptions}</select>
          </label>

          <label>Title
            <input id="crc-title" type="text" placeholder="Dentist appointment"/>
          </label>

          <label class="row">
            <input id="crc-allday" type="checkbox"/>
            <span>All-day event</span>
          </label>

          <div class="grid2">
            <label>Start
              <input id="crc-start" type="datetime-local" value="${nextHourLocal()}"/>
            </label>
            <label>End
              <input id="crc-end" type="datetime-local" value="${nextHourLocal(60)}"/>
            </label>
          </div>

          <label>Location
            <input id="crc-loc" type="text" placeholder="Optional"/>
          </label>

          <label>Description
            <textarea id="crc-desc" rows="2" placeholder="Optional"></textarea>
          </label>

          <div class="section">Reminder</div>
          <div id="crc-timed" class="chips">${presetHtml(TIMED_PRESETS, "timed")}</div>
          <div id="crc-allday-presets" class="chips" style="display:none">
            ${presetHtml(ALLDAY_PRESETS, "allday")}
          </div>
          <label id="crc-custom-row">Custom (minutes before)
            <input id="crc-custom" type="number" min="1" placeholder="e.g. 45"/>
          </label>

          <mwc-button raised id="crc-save">Create appointment</mwc-button>
          <div id="crc-status"></div>
        </div>
      </ha-card>
      <style>
        .crc { padding: 0 16px 16px; display: flex; flex-direction: column; gap: 10px; }
        .crc label { display: flex; flex-direction: column; font-size: 0.9em;
          color: var(--secondary-text-color); gap: 4px; }
        .crc label.row { flex-direction: row; align-items: center; gap: 8px;
          color: var(--primary-text-color); }
        .crc input, .crc select, .crc textarea {
          font: inherit; color: var(--primary-text-color);
          background: var(--card-background-color);
          border: 1px solid var(--divider-color); border-radius: 8px;
          padding: 8px; }
        .crc .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .crc .section { font-weight: 600; color: var(--primary-text-color);
          margin-top: 4px; }
        .crc .chips { display: flex; flex-wrap: wrap; gap: 6px; }
        .crc .chip { flex-direction: row !important; align-items: center;
          border: 1px solid var(--divider-color); border-radius: 16px;
          padding: 4px 10px; cursor: pointer; user-select: none; }
        .crc .chip:has(input:checked) {
          background: var(--primary-color); border-color: var(--primary-color); }
        .crc .chip:has(input:checked) span { color: var(--text-primary-color); }
        .crc .chip input { display: none; }
        #crc-status { min-height: 1.2em; font-size: 0.9em; }
        #crc-status.ok { color: var(--success-color, #4caf50); }
        #crc-status.err { color: var(--error-color, #f44336); }
      </style>
    `;

    this.querySelector("#crc-allday").addEventListener("change", (ev) => {
      const allDay = ev.target.checked;
      this.querySelector("#crc-timed").style.display = allDay ? "none" : "flex";
      this.querySelector("#crc-allday-presets").style.display = allDay
        ? "flex"
        : "none";
      this.querySelector("#crc-custom-row").style.display = allDay
        ? "none"
        : "flex";
    });

    this.querySelector("#crc-start").addEventListener("change", (ev) => {
      // Keep end 1h after start if end is now before start
      const endEl = this.querySelector("#crc-end");
      if (endEl.value <= ev.target.value) {
        const d = new Date(ev.target.value);
        d.setHours(d.getHours() + 1);
        endEl.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(
          d.getDate()
        )}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
      }
    });

    this.querySelector("#crc-save").addEventListener("click", () =>
      this._save()
    );
  }

  _collectReminderTag(allDay) {
    const container = allDay ? "#crc-allday-presets" : "#crc-timed";
    const minutes = Array.from(
      this.querySelectorAll(`${container} input:checked`)
    ).map((el) => parseInt(el.value, 10));
    if (!allDay) {
      const custom = parseInt(this.querySelector("#crc-custom").value, 10);
      if (custom > 0) minutes.push(custom);
    }
    const unique = [...new Set(minutes)].sort((a, b) => a - b);
    if (!unique.length) return "";
    return `#remind ${unique.map(fmtToken).join(" ")}`;
  }

  async _save() {
    const status = this.querySelector("#crc-status");
    status.className = "";
    status.textContent = "";

    const entityId = this.querySelector("#crc-cal").value;
    const title = this.querySelector("#crc-title").value.trim();
    const allDay = this.querySelector("#crc-allday").checked;
    const start = this.querySelector("#crc-start").value;
    const end = this.querySelector("#crc-end").value;
    const location = this.querySelector("#crc-loc").value.trim();
    const desc = this.querySelector("#crc-desc").value.trim();

    if (!entityId || !title || !start) {
      status.className = "err";
      status.textContent = "Calendar, title and start time are required.";
      return;
    }

    const tag = this._collectReminderTag(allDay);
    const description = [desc, tag].filter(Boolean).join("\n\n");

    const data = { entity_id: entityId, summary: title };
    if (description) data.description = description;
    if (location) data.location = location;

    if (allDay) {
      const startDate = start.slice(0, 10);
      const endDate = end ? end.slice(0, 10) : startDate;
      data.start_date = startDate;
      // end_date is exclusive per iCal convention
      data.end_date = addDays(endDate >= startDate ? endDate : startDate, 1);
    } else {
      data.start_date_time = toServiceDateTime(start);
      data.end_date_time = toServiceDateTime(end && end > start ? end : start);
    }

    try {
      await this._hass.callService("calendar", "create_event", data);
      status.className = "ok";
      status.textContent = tag
        ? "Appointment created — reminder scheduled ✓"
        : "Appointment created ✓";
      this.querySelector("#crc-title").value = "";
      this.querySelector("#crc-desc").value = "";
      this.querySelector("#crc-loc").value = "";
      this.querySelector("#crc-custom").value = "";
    } catch (err) {
      status.className = "err";
      status.textContent = `Failed: ${
        err.message || err
      } (is this calendar writable?)`;
    }
  }
}

customElements.define("calendar-reminder-card", CalendarReminderCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "calendar-reminder-card",
  name: "Calendar Reminder Card",
  description:
    "Create calendar appointments with built-in reminder notifications.",
});

console.info(
  "%c CALENDAR-REMINDER-CARD %c loaded ",
  "background:#03a9f4;color:#fff;border-radius:4px 0 0 4px;padding:2px 6px",
  "background:#555;color:#fff;border-radius:0 4px 4px 0;padding:2px 6px"
);
