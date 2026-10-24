// node --test tests/js/
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  apply,
  canonical,
  parse,
  serialize,
  sortTokens,
} from "../../custom_components/calendar_reminders/www/remind-line.js";

test("canonical tokens", () => {
  const cases = {
    0: "0",
    15: "15m",
    "15m": "15m",
    "90m": "90m",
    "120m": "2h",
    "2h": "2h",
    "1d": "1d",
    "14d": "2w",
    "1w": "1w",
    "0d": "0d",
    "0d@7:30": "0d@07:30",
    "1D@18:00": "1d@18:00",
  };
  for (const [input, expected] of Object.entries(cases)) {
    assert.equal(canonical(input), expected, input);
  }
  for (const bad of ["1d@24:00", "1d@07:60", "1h@18:00", "-1h", "1.5h", "soon", "12345m", "@"]) {
    assert.equal(canonical(bad), null, bad);
  }
});

test("sort order is earliest first", () => {
  assert.deepEqual(sortTokens(["1h", "1w", "0", "2d"]), ["1w", "2d", "1h", "0"]);
  assert.deepEqual(sortTokens(["0d@07:30", "1d@18:00"]), ["1d@18:00", "0d@07:30"]);
  assert.deepEqual(sortTokens(["1d@18:00", "1d@08:00"]), ["1d@08:00", "1d@18:00"]);
});

test("parse finds only the last non-blank line", () => {
  assert.equal(parse(null), null);
  assert.equal(parse("Bring cake"), null);
  assert.equal(parse("#remind 1h\nBring cake"), null);
  assert.equal(parse("#reminder 1h"), null);
  assert.deepEqual(parse("Notes\r\n#REMIND 60m @Anna @ben @anna!\n\n").offsets, ["1h"]);
  assert.deepEqual(parse("Notes\n#remind 60m @Anna @ben @anna!").devices, ["anna", "ben"]);
  assert.equal(parse("#remind 30m!").important, true);
});

test("parse: off, unknown tokens, aliases filter, Google HTML", () => {
  assert.deepEqual(parse("#remind off 1h"), {
    offsets: [],
    devices: [],
    important: false,
    off: true,
    unknown: ["1h"],
  });
  const line = parse("#remind 1h soon @bob", ["anna", "ben"]);
  assert.deepEqual(line.offsets, ["1h"]);
  assert.deepEqual(line.devices, []);
  assert.deepEqual(line.unknown, ["soon", "@bob"]);
  assert.deepEqual(parse("<p>Notes</p><p>#remind&nbsp;1h @ben</p>").devices, ["ben"]);
});

test("serialize", () => {
  assert.equal(serialize({ offsets: ["30m", "2h", "1d"] }), "#remind 1d 2h 30m");
  assert.equal(
    serialize({ offsets: ["5m"], devices: ["kitchen"], important: true }),
    "#remind 5m @kitchen !",
  );
  assert.equal(serialize({ off: true }), "#remind off");
  assert.equal(serialize({ offsets: [], devices: ["anna"] }), null);
});

test("apply replaces, adds and removes the line", () => {
  assert.equal(apply("", "#remind 1h"), "#remind 1h");
  assert.equal(apply(undefined, "#remind 1h"), "#remind 1h");
  assert.equal(apply("Bring cake", "#remind 1h"), "Bring cake\n#remind 1h");
  assert.equal(apply("Bring cake\n#remind 2h\n \n", "#remind 1h"), "Bring cake\n#remind 1h");
  assert.equal(apply("#remind 2h\nBring cake", "#remind 1h"), "#remind 2h\nBring cake\n#remind 1h");
  assert.equal(apply("Bring cake\n\n#remind 2h", null), "Bring cake");
  assert.equal(apply("#remind 2h", null), "");
});
