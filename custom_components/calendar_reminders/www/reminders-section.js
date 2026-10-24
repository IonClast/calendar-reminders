// <calendar-reminders-section>: pick when and who, and the section writes the
// "#remind" line into the event description. Used inside Home Assistant's own
// Add/Edit event dialog (dialog-ext.js) and by the card.
//
// Host API:
//   section.hass = hass;            // to load devices from the integration
//   section.allDay = true|false;    // offers all-day choices
//   section.load(description, isNew)  // a new dialog/event was opened
//   section.sync(description)       // the description changed outside the section
//   "line-changed" event, detail {description}: the new description to store

import { apply, canonical, parse, parseOffset, serialize, sortTokens } from "./remind-line.js";

const TIMED_PRESETS = ["0", "10m", "30m", "1h", "2h", "1d"];
const ALL_DAY_PRESETS = ["1d", "2d", "1w", "0d@07:00"];

const STRINGS = {
  en: {
    title: "Reminders",
    when: "When",
    who: "Who",
    atStart: "At start",
    before: (x) => `${x} before`,
    dayBeforeAt: (n, t) => (n === 1 ? `Day before at ${t}` : `${n} days before at ${t}`),
    weekBeforeAt: (n, t) => (n === 1 ? `Week before at ${t}` : `${n} weeks before at ${t}`),
    sameDayAt: (t) => `Same day at ${t}`,
    min: "min",
    hour: (n) => (n === 1 ? "1 hour" : `${n} hours`),
    hShort: "h",
    day: (n) => (n === 1 ? "1 day" : `${n} days`),
    week: (n) => (n === 1 ? "1 week" : `${n} weeks`),
    other: "Other",
    add: "Add",
    unitMin: "minutes",
    unitHour: "hours",
    unitDay: "days",
    unitWeek: "weeks",
    daysBefore: "days before, at",
    important: "Ring even on silent",
    pickWho: "Pick who gets the reminder.",
    defaults: "No one picked: the default devices get it.",
    notUnderstood: (x) => `Not understood in the line: ${x}`,
    off: "Reminders are off for this event (#remind off).",
  },
  nb: {
    title: "Påminnelser",
    when: "Når",
    who: "Hvem",
    atStart: "Ved start",
    before: (x) => `${x} før`,
    dayBeforeAt: (n, t) => (n === 1 ? `Dagen før kl. ${t}` : `${n} dager før kl. ${t}`),
    weekBeforeAt: (n, t) => (n === 1 ? `Uka før kl. ${t}` : `${n} uker før kl. ${t}`),
    sameDayAt: (t) => `Samme dag kl. ${t}`,
    min: "min",
    hour: (n) => (n === 1 ? "1 time" : `${n} timer`),
    hShort: "t",
    day: (n) => (n === 1 ? "1 dag" : `${n} dager`),
    week: (n) => (n === 1 ? "1 uke" : `${n} uker`),
    other: "Annet",
    add: "Legg til",
    unitMin: "minutter",
    unitHour: "timer",
    unitDay: "dager",
    unitWeek: "uker",
    daysBefore: "dager før, kl.",
    important: "Ring selv på lydløs",
    pickWho: "Velg hvem som skal få påminnelsen.",
    defaults: "Ingen valgt: standardenhetene får den.",
    notUnderstood: (x) => `Ikke forstått i linjen: ${x}`,
    off: "Påminnelser er slått av for denne hendelsen (#remind off).",
  },
};

const configCache = new WeakMap(); // hass.connection -> Promise<config>

/** Load the integration's devices and defaults once per connection. */
export function loadConfig(hass) {
  const key = hass.connection || hass;
  if (!configCache.has(key)) {
    configCache.set(
      key,
      hass.callWS({ type: "calendar_reminders/config" }).catch(() => ({ loaded: false })),
    );
  }
  return configCache.get(key);
}

export function language(hass) {
  const lang = (hass?.locale?.language || hass?.language || "en").toLowerCase();
  return lang.startsWith("nb") || lang.startsWith("no") || lang.startsWith("nn") ? "nb" : "en";
}

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** Human label for a canonical token. */
export function offsetLabel(token, s, allDay, allDayTime) {
  const o = parseOffset(token);
  if (!o) return token;
  if (o.unit === "d@") return o.amount === 0 ? s.sameDayAt(o.at) : s.dayBeforeAt(o.amount, o.at);
  if (o.unit === "d") {
    if (allDay) {
      if (o.amount === 0) return s.sameDayAt(allDayTime);
      return o.amount % 7 === 0
        ? s.weekBeforeAt(o.amount / 7, allDayTime)
        : s.dayBeforeAt(o.amount, allDayTime);
    }
    return s.before(o.amount % 7 === 0 && o.amount ? s.week(o.amount / 7) : s.day(o.amount));
  }
  if (o.amount === 0) return s.atStart;
  if (o.amount < 60) return s.before(`${o.amount} ${s.min}`);
  const h = Math.floor(o.amount / 60);
  const m = o.amount % 60;
  return s.before(m ? `${h} ${s.hShort} ${m} ${s.min}` : s.hour(h));
}

class CalendarRemindersSection extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    this._allDay = false;
    this.description = "";
    this._offsets = new Set();
    this._devices = new Set();
    this._implicitDevices = false; // line without @: the default devices
    this._important = false;
    this._off = false;
    this._unknown = [];
    this._pending = null;
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first && hass) {
      loadConfig(hass).then((config) => {
        this._config = config;
        if (this._pending) {
          const [description, isNew] = this._pending;
          this._pending = null;
          this.load(description, isNew);
        } else {
          this._render();
        }
      });
    }
  }

  get hass() {
    return this._hass;
  }

  set allDay(value) {
    if (Boolean(value) !== this._allDay) {
      this._allDay = Boolean(value);
      this._render();
    }
  }

  /** A dialog or form opened for an event (new or existing). */
  load(description, isNew) {
    this.description = description || "";
    if (!this._config) {
      this._pending = [this.description, isNew];
      return;
    }
    this._readLine(isNew);
    this._render();
  }

  /** The description changed elsewhere (typed in the textarea): follow it. */
  sync(description) {
    if ((description || "") === this.description) return;
    this.description = description || "";
    if (this._config) {
      this._readLine(false);
      this._render();
    }
  }

  _readLine(isNew) {
    const config = this._config;
    const aliases = (config.devices || []).map((d) => d.alias);
    const line = parse(this.description, aliases);
    this._off = Boolean(line?.off);
    this._offsets = new Set(line && !line.off ? line.offsets : []);
    this._important = Boolean(line?.important);
    this._unknown = line ? line.unknown : [];
    if (line && line.devices.length) {
      this._devices = new Set(line.devices);
      this._implicitDevices = false;
    } else if (line && line.offsets.length) {
      this._devices = new Set(config.default_devices || []);
      this._implicitDevices = true;
    } else {
      const own = (config.devices || []).filter((d) => d.own).map((d) => d.alias);
      this._devices = new Set(own.length ? own : config.default_devices || []);
      this._implicitDevices = !own.length && isNew;
    }
  }

  _emit() {
    const devices = this._implicitDevices ? [] : [...this._devices];
    let line = null;
    if (this._offsets.size && (this._implicitDevices || devices.length)) {
      line = serialize({ offsets: [...this._offsets], devices, important: this._important });
    }
    this._off = false;
    this._unknown = [];
    this.description = apply(this.description, line);
    this.dispatchEvent(
      new CustomEvent("line-changed", { detail: { description: this.description }, bubbles: false }),
    );
    this._render();
  }

  _onClick(ev) {
    const el = ev.composedPath().find((n) => n instanceof HTMLElement && n.dataset && n.dataset.act);
    if (!el) return;
    const { act, value } = el.dataset;
    if (act === "offset") {
      if (this._offsets.has(value)) this._offsets.delete(value);
      else this._offsets.add(value);
      this._emit();
    } else if (act === "device") {
      if (this._implicitDevices) this._implicitDevices = false;
      if (this._devices.has(value)) this._devices.delete(value);
      else this._devices.add(value);
      this._emit();
    } else if (act === "add") {
      const root = this.shadowRoot;
      const n = Number(root.querySelector("#n")?.value);
      if (!Number.isInteger(n) || n < 0) return;
      let token;
      if (this._allDay) {
        const time = root.querySelector("#t")?.value || this._config.all_day_time || "18:00";
        token = canonical(`${n}d@${time}`);
      } else {
        token = canonical(`${n}${root.querySelector("#u")?.value || "m"}`);
      }
      if (token) {
        this._offsets.add(token);
        this._emit();
      }
    }
  }

  _onChange(ev) {
    if (ev.target?.id === "important") {
      this._important = ev.target.checked;
      if (this._offsets.size) this._emit();
      else this._render();
    }
  }

  _render() {
    const config = this._config;
    if (!config || !config.loaded) {
      this.shadowRoot.innerHTML = "";
      this.style.display = "none";
      return;
    }
    this.style.display = "";
    const s = STRINGS[language(this._hass)];
    const allDayTime = config.all_day_time || "18:00";
    const presets = this._allDay ? ALL_DAY_PRESETS : TIMED_PRESETS;
    const tokens = sortTokens(new Set([...presets, ...this._offsets]));
    const chip = (act, value, label, on) =>
      `<button type="button" class="chip${on ? " on" : ""}" data-act="${act}" data-value="${esc(value)}" aria-pressed="${on}">${esc(label)}</button>`;
    const offsetChips = tokens
      .map((t) => chip("offset", t, offsetLabel(t, s, this._allDay, allDayTime), this._offsets.has(t)))
      .join("");
    const deviceChips = (config.devices || [])
      .map((d) => chip("device", d.alias, d.name, this._devices.has(d.alias)))
      .join("");
    const custom = this._allDay
      ? `<input id="n" type="number" min="0" max="99" value="1" aria-label="${esc(s.unitDay)}">
         <span>${esc(s.daysBefore)}</span>
         <input id="t" type="time" value="${esc(allDayTime)}">`
      : `<input id="n" type="number" min="0" max="9999" value="15" aria-label="${esc(s.other)}">
         <select id="u">
           <option value="m">${esc(s.unitMin)}</option><option value="h">${esc(s.unitHour)}</option>
           <option value="d">${esc(s.unitDay)}</option><option value="w">${esc(s.unitWeek)}</option>
         </select>`;
    let note = "";
    if (this._off) note = s.off;
    else if (this._offsets.size && !this._implicitDevices && !this._devices.size) note = s.pickWho;
    const unknown = this._unknown.length ? `<p class="note">${esc(s.notUnderstood(this._unknown.join(" ")))}</p>` : "";
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; margin: 8px 0 4px; }
        h3 { font: var(--ha-font-weight-medium, 500) var(--ha-font-size-m, 14px) / 1.4 var(--ha-font-family-body, inherit);
             margin: 0 0 6px; color: var(--primary-text-color); }
        .label { font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); margin: 8px 0 4px; }
        .chips { display: flex; flex-wrap: wrap; gap: 6px; }
        .chip { font: inherit; font-size: var(--ha-font-size-s, 13px); cursor: pointer; padding: 6px 12px;
                border-radius: 16px; border: 1px solid var(--divider-color, #ccc);
                background: var(--card-background-color, transparent); color: var(--primary-text-color); }
        .chip.on { background: var(--primary-color); border-color: var(--primary-color);
                   color: var(--text-primary-color, #fff); }
        .chip:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
        .custom { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 8px;
                  color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 13px); }
        input, select { font: inherit; padding: 4px 6px; border-radius: 4px; color: var(--primary-text-color);
                        background: var(--card-background-color, transparent); border: 1px solid var(--divider-color, #ccc); }
        input[type="number"] { width: 4.5em; }
        .add { font: inherit; cursor: pointer; padding: 4px 10px; border-radius: 4px; border: none;
               background: var(--secondary-background-color, #eee); color: var(--primary-text-color); }
        .important { display: flex; align-items: center; gap: 8px; margin-top: 10px; color: var(--primary-text-color); }
        .note { margin: 6px 0 0; font-size: var(--ha-font-size-s, 12px); color: var(--warning-color, #b26a00); }
      </style>
      <h3>${esc(s.title)}</h3>
      <div class="label">${esc(s.when)}</div>
      <div class="chips">${offsetChips}</div>
      <div class="custom">${custom}<button type="button" class="add" data-act="add">${esc(s.add)}</button></div>
      <div class="label">${esc(s.who)}</div>
      <div class="chips">${deviceChips}</div>
      <label class="important"><input id="important" type="checkbox" ${this._important ? "checked" : ""}>${esc(s.important)}</label>
      ${note ? `<p class="note">${esc(note)}</p>` : ""}
      ${unknown}
    `;
  }
}

if (!customElements.get("calendar-reminders-section")) {
  customElements.define("calendar-reminders-section", CalendarRemindersSection);
}
