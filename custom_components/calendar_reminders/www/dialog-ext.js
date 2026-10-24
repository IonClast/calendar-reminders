// Adds a Reminders section to Home Assistant's own Add/Edit event dialog
// (dialog-calendar-event-editor: Calendar panel, calendar card, Companion app).
//
// The dialog is loaded lazily and reused between openings, so this:
// - wraps showDialog() to mark a new opening (new or existing event),
// - wraps updated() to keep the section right after the description field and
//   to follow the dialog's state (all day, description typed by hand),
// - writes the line by setting the description field and firing "change",
//   which the dialog handles like typing (it updates _description and Save).
// If anything it relies on is missing, it does nothing and the dialog works as usual.

import "./reminders-section.js";

const TAG = "dialog-calendar-event-editor";
const SECTION = "calendar-reminders-section";

function sync(dialog) {
  const root = dialog.shadowRoot;
  if (!root || !dialog._params || !dialog.hass) return;
  const field = root.querySelector('ha-textarea[name="description"]');
  if (!field) return;
  let section = root.querySelector(SECTION);
  const fresh = !section;
  if (fresh) {
    section = document.createElement(SECTION);
    section.addEventListener("line-changed", (ev) => {
      field.value = ev.detail.description;
      field.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
    });
  }
  if (section.previousElementSibling !== field) field.after(section);
  section.hass = dialog.hass;
  section.allDay = Boolean(dialog._allDay);
  const description = dialog._description || "";
  // The first opening can render before the patch is in place: a new section loads too.
  if (dialog.__calremOpened || fresh) {
    dialog.__calremOpened = false;
    section.load(description, dialog._params.entry === undefined);
  } else {
    section.sync(description);
  }
}

function patch(cls) {
  if (cls.prototype.__calremPatched) return;
  cls.prototype.__calremPatched = true;

  const showDialog = cls.prototype.showDialog;
  cls.prototype.showDialog = function (...args) {
    const result = showDialog.apply(this, args);
    this.__calremOpened = true;
    return result;
  };

  const updated = cls.prototype.updated;
  cls.prototype.updated = function (changed) {
    if (updated) updated.call(this, changed);
    try {
      sync(this);
    } catch (err) {
      // Never break the dialog itself.
      console.warn("calendar_reminders: Reminders section skipped", err);
    }
  };

  // A dialog that is already open when this loads.
  const ha = document.querySelector("home-assistant");
  for (const dialog of ha?.shadowRoot?.querySelectorAll(TAG) || []) {
    dialog.__calremOpened = true;
    dialog.requestUpdate?.();
  }
}

customElements.whenDefined(TAG).then(() => patch(customElements.get(TAG)));
