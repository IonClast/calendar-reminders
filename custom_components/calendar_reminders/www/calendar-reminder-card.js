// custom:calendar-reminder-card: create and edit calendar events with
// reminders, for dashboards and wall panels. Reminders use the same section as
// Home Assistant's own event dialog (reminders-section.js).
//
//   type: custom:calendar-reminder-card
//   title: New appointment      # optional
//   calendars:                  # optional; default: the calendars the integration watches
//     - calendar.family
//   days: 14                    # optional; how far ahead the upcoming list looks

import { language, loadConfig } from "./reminders-section.js";

const CREATE = 1;
const UPDATE = 4;

const STRINGS = {
  en: {
    title: "New appointment",
    editTitle: "Edit appointment",
    summary: "Title",
    calendar: "Calendar",
    allDay: "All day",
    start: "Start",
    end: "End",
    location: "Location",
    description: "Description",
    repeat: "Repeat",
    repeats: { "": "Does not repeat", DAILY: "Daily", WEEKLY: "Weekly", MONTHLY: "Monthly", YEARLY: "Yearly" },
    create: "Create",
    save: "Save",
    cancel: "Cancel",
    upcoming: "Upcoming",
    none: "No events in the next days.",
    edit: "Edit",
    noEdit: "This calendar can't be edited from Home Assistant.",
    occurrence: "Changes apply to this occurrence only.",
    created: "Created.",
    saved: "Saved.",
    needSummary: "Enter a title.",
    endBeforeStart: "The end is before the start.",
    noCalendar: "No calendar that allows new events.",
  },
  nb: {
    title: "Ny avtale",
    editTitle: "Endre avtale",
    summary: "Tittel",
    calendar: "Kalender",
    allDay: "Hele dagen",
    start: "Start",
    end: "Slutt",
    location: "Sted",
    description: "Beskrivelse",
    repeat: "Gjenta",
    repeats: { "": "Gjentas ikke", DAILY: "Daglig", WEEKLY: "Ukentlig", MONTHLY: "Månedlig", YEARLY: "Årlig" },
    create: "Opprett",
    save: "Lagre",
    cancel: "Avbryt",
    upcoming: "Kommende",
    none: "Ingen hendelser de neste dagene.",
    edit: "Endre",
    noEdit: "Denne kalenderen kan ikke endres fra Home Assistant.",
    occurrence: "Endringen gjelder bare denne forekomsten.",
    created: "Opprettet.",
    saved: "Lagret.",
    needSummary: "Skriv inn en tittel.",
    endBeforeStart: "Slutt er før start.",
    noCalendar: "Ingen kalender som tillater nye hendelser.",
  },
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const hm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const addDays = (dateStr, n) => {
  const d = new Date(`${dateStr}T12:00:00`);
  d.setDate(d.getDate() + n);
  return ymd(d);
};

/** "2026-11-02" + "10:00" -> "2026-11-02T10:00:00+01:00" in the browser's time zone. */
function localIso(date, time) {
  const d = new Date(`${date}T${time}:00`);
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  return `${date}T${time}:00${sign}${pad(Math.floor(Math.abs(off) / 60))}:${pad(Math.abs(off) % 60)}`;
}

class CalendarReminderCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._watched = null;
    this._events = [];
    this._editing = null; // the event being edited, or null for a new one
    this._status = "";
    this._built = false;
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
  }

  setConfig(config) {
    this._config = config || {};
    this._built = false;
    if (this._hass) this._build();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      loadConfig(hass).then((config) => {
        this._watched = config.loaded ? config.calendars : null;
        this._build();
        this._loadEvents();
      });
    }
    const section = this.shadowRoot.querySelector("calendar-reminders-section");
    if (section) section.hass = hass;
  }

  getCardSize() {
    return 9;
  }

  static getStubConfig() {
    return {};
  }

  get _s() {
    return STRINGS[language(this._hass)];
  }

  _calendars() {
    const states = this._hass?.states || {};
    const ids = this._config.calendars?.length
      ? this._config.calendars
      : this._watched?.length
        ? this._watched
        : Object.keys(states).filter((id) => id.startsWith("calendar."));
    return ids
      .filter((id) => states[id])
      .map((id) => ({
        id,
        name: states[id].attributes.friendly_name || id,
        features: states[id].attributes.supported_features || 0,
      }));
  }

  _build() {
    if (!this._hass) return;
    const s = this._s;
    const writable = this._calendars().filter((c) => c.features & CREATE);
    const now = new Date();
    now.setMinutes(0, 0, 0);
    now.setHours(now.getHours() + 1);
    const later = new Date(now.getTime() + 3600 * 1000);
    const e = this._editing;
    const calOptions = (e ? this._calendars().filter((c) => c.id === e.calendar) : writable)
      .map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`)
      .join("");
    const repeatOptions = Object.entries(s.repeats)
      .map(([v, label]) => `<option value="${v}">${esc(label)}</option>`)
      .join("");
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        h2 { margin: 0 0 12px; font: var(--ha-font-weight-normal, 400) var(--ha-font-size-xl, 20px) / 1.3 var(--ha-font-family-body, inherit); }
        label { display: block; font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); margin: 10px 0 3px; }
        input, select, textarea { font: inherit; width: 100%; box-sizing: border-box; padding: 8px; border-radius: 4px;
          border: 1px solid var(--divider-color, #ccc); background: var(--card-background-color, transparent); color: var(--primary-text-color); }
        textarea { min-height: 64px; resize: vertical; }
        .row { display: flex; gap: 8px; }
        .row > * { flex: 1; }
        .check { display: flex; align-items: center; gap: 8px; margin-top: 10px; color: var(--primary-text-color); font-size: inherit; }
        .check input { width: auto; }
        .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; }
        button.primary, button.plain { font: inherit; cursor: pointer; padding: 8px 16px; border-radius: 18px; border: none; }
        button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        button.plain { background: none; color: var(--primary-color); }
        .status { margin: 8px 0 0; color: var(--secondary-text-color); }
        .status.error { color: var(--error-color, #c00); }
        .hint { font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); margin: 6px 0 0; }
        ul { list-style: none; margin: 0; padding: 0; }
        li { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 0;
             border-top: 1px solid var(--divider-color, #eee); }
        li .when { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); }
        h3 { margin: 18px 0 4px; font-size: var(--ha-font-size-m, 14px); font-weight: var(--ha-font-weight-medium, 500); }
      </style>
      <ha-card>
        <h2>${esc(e ? s.editTitle : this._config.title || s.title)}</h2>
        ${writable.length || e ? "" : `<p class="status error">${esc(s.noCalendar)}</p>`}
        <label for="summary">${esc(s.summary)}</label>
        <input id="summary" value="${esc(e?.summary || "")}">
        <label for="calendar">${esc(s.calendar)}</label>
        <select id="calendar" ${e ? "disabled" : ""}>${calOptions}</select>
        <label class="check"><input id="allday" type="checkbox" ${e?.allDay ? "checked" : ""}>${esc(s.allDay)}</label>
        <label>${esc(s.start)}</label>
        <div class="row"><input id="sd" type="date" value="${e?.sd || ymd(now)}"><input id="st" type="time" value="${e?.st || hm(now)}"></div>
        <label>${esc(s.end)}</label>
        <div class="row"><input id="ed" type="date" value="${e?.ed || ymd(later)}"><input id="et" type="time" value="${e?.et || hm(later)}"></div>
        <label for="location">${esc(s.location)}</label>
        <input id="location" value="${esc(e?.location || "")}">
        <label for="description">${esc(s.description)}</label>
        <textarea id="description">${esc(e?.description || "")}</textarea>
        <calendar-reminders-section></calendar-reminders-section>
        ${e ? (e.recurrenceId ? `<p class="hint">${esc(s.occurrence)}</p>` : "") : `<label for="repeat">${esc(s.repeat)}</label><select id="repeat">${repeatOptions}</select>`}
        <div class="actions">
          ${e ? `<button class="plain" data-act="cancel">${esc(s.cancel)}</button>` : ""}
          <button class="primary" data-act="save">${esc(e ? s.save : s.create)}</button>
        </div>
        <p class="status" id="status">${esc(this._status)}</p>
        <h3>${esc(s.upcoming)}</h3>
        <ul id="upcoming"></ul>
      </ha-card>
    `;
    const section = this.shadowRoot.querySelector("calendar-reminders-section");
    section.hass = this._hass;
    section.allDay = Boolean(e?.allDay);
    section.load(e?.description || "", !e);
    section.addEventListener("line-changed", (ev) => {
      this.shadowRoot.querySelector("#description").value = ev.detail.description;
    });
    this._toggleTimes();
    this._renderEvents();
    this._built = true;
  }

  _toggleTimes() {
    const allDay = this.shadowRoot.querySelector("#allday")?.checked;
    for (const id of ["#st", "#et"]) {
      const el = this.shadowRoot.querySelector(id);
      if (el) el.style.display = allDay ? "none" : "";
    }
  }

  _onChange(ev) {
    const id = ev.target?.id;
    if (id === "allday") {
      this._toggleTimes();
      this.shadowRoot.querySelector("calendar-reminders-section").allDay = ev.target.checked;
    } else if (id === "description") {
      this.shadowRoot.querySelector("calendar-reminders-section").sync(ev.target.value);
    } else if (id === "calendar") {
      this._loadEvents();
    }
  }

  _onClick(ev) {
    const el = ev.composedPath().find((n) => n instanceof HTMLElement && n.dataset?.act);
    if (!el) return;
    if (el.dataset.act === "save") this._save();
    else if (el.dataset.act === "cancel") this._startNew();
    else if (el.dataset.act === "edit") this._startEdit(Number(el.dataset.index));
  }

  _setStatus(text, error = false) {
    this._status = text;
    const el = this.shadowRoot.querySelector("#status");
    if (el) {
      el.textContent = text;
      el.classList.toggle("error", error);
    }
  }

  _startNew() {
    this._editing = null;
    this._status = "";
    this._build();
  }

  _startEdit(index) {
    const ev = this._events[index];
    if (!ev) return;
    const allDay = Boolean(ev.start.date);
    const start = allDay ? null : new Date(ev.start.dateTime);
    const end = allDay ? null : new Date(ev.end.dateTime);
    this._editing = {
      calendar: ev.calendar,
      uid: ev.uid,
      recurrenceId: ev.recurrence_id || null,
      summary: ev.summary,
      description: ev.description || "",
      location: ev.location || "",
      allDay,
      sd: allDay ? ev.start.date : ymd(start),
      st: allDay ? "09:00" : hm(start),
      ed: allDay ? addDays(ev.end.date, -1) : ymd(end),
      et: allDay ? "10:00" : hm(end),
    };
    this._status = "";
    this._build();
    this.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }

  _read() {
    const q = (id) => this.shadowRoot.querySelector(id);
    const allDay = q("#allday").checked;
    const sd = q("#sd").value;
    const ed = q("#ed").value || sd;
    const event = {
      summary: q("#summary").value.trim(),
      description: q("#description").value,
      location: q("#location").value.trim(),
    };
    if (allDay) {
      event.dtstart = sd;
      event.dtend = addDays(ed, 1); // exclusive end
    } else {
      event.dtstart = localIso(sd, q("#st").value || "00:00");
      event.dtend = localIso(ed, q("#et").value || "00:00");
    }
    const repeat = q("#repeat")?.value;
    if (repeat) event.rrule = `FREQ=${repeat}`;
    if (!event.description) delete event.description;
    if (!event.location) delete event.location;
    return { calendar: this._editing?.calendar || q("#calendar").value, event };
  }

  async _save() {
    const s = this._s;
    const { calendar, event } = this._read();
    if (!event.summary) return this._setStatus(s.needSummary, true);
    if (new Date(event.dtend) <= new Date(event.dtstart)) return this._setStatus(s.endBeforeStart, true);
    try {
      if (this._editing) {
        const msg = { type: "calendar/event/update", entity_id: calendar, uid: this._editing.uid, event };
        if (this._editing.recurrenceId) msg.recurrence_id = this._editing.recurrenceId;
        await this._hass.callWS(msg);
        this._editing = null;
        this._status = s.saved;
      } else {
        await this._hass.callWS({ type: "calendar/event/create", entity_id: calendar, event });
        this._status = s.created;
      }
      this._build();
      this._loadEvents();
    } catch (err) {
      this._setStatus(err?.message || String(err), true);
    }
  }

  async _loadEvents() {
    if (!this._hass) return;
    const days = Number(this._config.days) || 14;
    const start = new Date();
    const end = new Date(start.getTime() + days * 86400 * 1000);
    const calendars = this._calendars();
    const results = await Promise.all(
      calendars.map((c) =>
        this._hass
          .callApi("GET", `calendars/${c.id}?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`)
          .then((events) => events.map((e) => ({ ...e, calendar: c.id, editable: Boolean(c.features & UPDATE) && Boolean(e.uid) })))
          .catch(() => []),
      ),
    );
    const when = (e) => new Date(e.start.dateTime || `${e.start.date}T00:00:00`).getTime();
    this._events = results.flat().sort((a, b) => when(a) - when(b)).slice(0, 20);
    this._renderEvents();
  }

  _renderEvents() {
    const list = this.shadowRoot.querySelector("#upcoming");
    if (!list) return;
    const s = this._s;
    const locale = this._hass?.locale?.language || undefined;
    if (!this._events.length) {
      list.innerHTML = `<li><span class="when">${esc(s.none)}</span></li>`;
      return;
    }
    list.innerHTML = this._events
      .map((e, i) => {
        const allDay = Boolean(e.start.date);
        const start = new Date(e.start.dateTime || `${e.start.date}T00:00:00`);
        const when = allDay
          ? start.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" })
          : start.toLocaleString(locale, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
        const reminder = /^\s*#remind\b/im.test((e.description || "").split(/\r?\n/).filter((l) => l.trim()).pop() || "") ? " ⏰" : "";
        const button = e.editable
          ? `<button class="plain" data-act="edit" data-index="${i}">${esc(s.edit)}</button>`
          : `<span class="when" title="${esc(s.noEdit)}">—</span>`;
        return `<li><div><div>${esc(e.summary)}${reminder}</div><div class="when">${esc(when)}</div></div>${button}</li>`;
      })
      .join("");
  }
}

if (!customElements.get("calendar-reminder-card")) {
  customElements.define("calendar-reminder-card", CalendarReminderCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "calendar-reminder-card",
    name: "Calendar Reminder Card",
    description: "Create and edit calendar events with reminders.",
  });
}
