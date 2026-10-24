// The "#remind" line, version 2: parse, write, and put it into a description.
// A JavaScript port of remind_line.py; both produce the same canonical text.
//
//   #remind <when>... [@device]... [!]
//   when  0 | <n>m | <n>h | <n>d | <n>w | <n>d@HH:MM | <n> (= minutes)
//   #remind off

const TAG_RE = /^\s*#remind\b(.*)$/i;
const OFFSET_RE = /^(\d{1,4})([mhdw]?)$/;
const AT_RE = /^(\d{1,2})d@(\d{1,2}):(\d{2})$/;
const ALIAS_RE = /^@([a-z0-9_]+)$/;
const HTML_BREAK_RE = /<br\s*\/?>|<\/p\s*>|<\/div\s*>/gi;
const HTML_TAG_RE = /<[^>]+>/g;

const pad = (n) => String(n).padStart(2, "0");

/** Canonical token for one offset, or null if the text isn't an offset. */
export function canonical(tok) {
  const o = parseOffset(String(tok).toLowerCase());
  return o ? o.token : null;
}

/**
 * Parse one offset token.
 * Returns {unit: "m"|"d"|"d@", amount, at: "HH:MM"|null, token} or null.
 */
export function parseOffset(tok) {
  let m = AT_RE.exec(tok);
  if (m) {
    const hh = Number(m[2]);
    const mm = Number(m[3]);
    if (hh > 23 || mm > 59) return null;
    return makeOffset("d@", Number(m[1]), `${pad(hh)}:${pad(mm)}`);
  }
  m = OFFSET_RE.exec(tok);
  if (!m) return null;
  const n = Number(m[1]);
  switch (m[2]) {
    case "h":
      return makeOffset("m", n * 60);
    case "d":
      return makeOffset("d", n);
    case "w":
      return makeOffset("d", n * 7);
    default:
      return makeOffset("m", n); // "m" or a bare number
  }
}

function makeOffset(unit, amount, at = null) {
  let token;
  if (unit === "d@") token = `${amount}d@${at}`;
  else if (unit === "d") token = amount && amount % 7 === 0 ? `${amount / 7}w` : `${amount}d`;
  else if (amount === 0) token = "0";
  else token = amount % 60 === 0 ? `${amount / 60}h` : `${amount}m`;
  return { unit, amount, at, token };
}

/** Sort key: days before minutes, larger before smaller, then time of day. */
function sortKey(o) {
  if (o.unit === "m") return [1, -o.amount, 0];
  const atMinutes = o.at ? Number(o.at.slice(0, 2)) * 60 + Number(o.at.slice(3)) : 0;
  return [0, -o.amount, atMinutes];
}

function compareKeys(a, b) {
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
}

/** Sort canonical tokens the way the line writes them (earliest first). */
export function sortTokens(tokens) {
  return [...tokens]
    .map((t) => parseOffset(t))
    .filter(Boolean)
    .sort((a, b) => compareKeys(sortKey(a), sortKey(b)))
    .map((o) => o.token);
}

function lastNonBlank(lines) {
  for (let i = lines.length - 1; i >= 0; i--) if (lines[i].trim()) return i;
  return -1;
}

/**
 * Parse the "#remind" line of a description.
 * Returns null without a line, else {offsets: [token], devices: [alias],
 * important, off, unknown: [token]}.
 */
export function parse(description, aliases = null) {
  if (!description) return null;
  let text = String(description);
  if (text.includes("<")) text = text.replace(HTML_BREAK_RE, "\n").replace(HTML_TAG_RE, "");
  text = text.replace(/&nbsp;| /g, " ").replace(/&amp;/g, "&");
  const lines = text.split(/\r?\n/);
  const idx = lastNonBlank(lines);
  if (idx < 0) return null;
  const m = TAG_RE.exec(lines[idx]);
  if (!m) return null;
  const known = aliases ? new Set(aliases.map((a) => a.toLowerCase())) : null;
  const tokens = m[1].toLowerCase().replaceAll("!", " ! ").split(/\s+/).filter(Boolean);
  if (tokens[0] === "off") {
    return { offsets: [], devices: [], important: false, off: true, unknown: tokens.slice(1) };
  }
  const offsets = [];
  const devices = [];
  const unknown = [];
  let important = false;
  for (const tok of tokens) {
    if (tok === "!") {
      important = true;
      continue;
    }
    const o = parseOffset(tok);
    if (o) {
      if (!offsets.includes(o.token)) offsets.push(o.token);
      continue;
    }
    const a = ALIAS_RE.exec(tok);
    if (a && (!known || known.has(a[1]))) {
      if (!devices.includes(a[1])) devices.push(a[1]);
    } else {
      unknown.push(tok);
    }
  }
  return { offsets, devices, important, off: false, unknown };
}

/** Canonical "#remind ..." text, or null when there is nothing to remind. */
export function serialize({ offsets = [], devices = [], important = false, off = false }) {
  if (off) return "#remind off";
  const tokens = sortTokens(offsets);
  if (!tokens.length) return null;
  const parts = ["#remind", ...tokens, ...devices.map((d) => `@${d}`)];
  if (important) parts.push("!");
  return parts.join(" ");
}

/** The description with its "#remind" line replaced, added or (line = null) removed. */
export function apply(description, line) {
  const lines = String(description || "").split(/\r?\n/);
  const idx = lastNonBlank(lines);
  let body;
  if (idx >= 0 && TAG_RE.test(lines[idx])) body = lines.slice(0, idx).join("\n").trimEnd();
  else body = String(description || "").trimEnd();
  if (!line) return body;
  return body ? `${body}\n${line}` : line;
}
