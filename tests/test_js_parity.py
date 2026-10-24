"""The JavaScript port of the #remind line must write exactly what Python writes."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from custom_components.calendar_reminders.remind_line import apply, parse

ROOT = Path(__file__).parent.parent
JS = ROOT / "custom_components/calendar_reminders/www/remind-line.js"

DESCRIPTIONS = [
    "#remind 30m 2h 1d",
    "#remind 15",
    "#remind 0",
    "#remind 90m 120m 1440m",
    "#remind 14d 7d 1w",
    "#remind 0d@7:30 1d@18:00 1d@08:00",
    "#remind 1h 1w 0 2d",
    "#remind 1h @Ben @anna @ben !",
    "#remind ! @kitchen 5m",
    "#remind 30m!",
    "#remind OFF 1h",
    "#remind @anna",
    "Notes\n\n#remind 1h soon @bob\n",
    "<p>Notes</p><p>#remind&nbsp;1h @ben</p>",
    "Bring cake",
    "#remind 2h\nBring cake",
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_js_matches_python() -> None:
    script = (
        f"import {{ parse, serialize, apply }} from {json.dumps(JS.as_uri())};\n"
        f"const inputs = {json.dumps(DESCRIPTIONS)};\n"
        "const out = inputs.map((d) => {\n"
        "  const line = parse(d);\n"
        "  const text = line ? serialize(line) : null;\n"
        "  return { line: text, applied: apply(d, text), removed: apply(d, null) };\n"
        "});\n"
        "console.log(JSON.stringify(out));\n"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    js = json.loads(result.stdout)
    for description, got in zip(DESCRIPTIONS, js, strict=True):
        line = parse(description)
        text = line.serialize() if line else None
        # Python writes "#remind 1h" for a line with offsets; JS writes null when
        # there is nothing to remind (no offsets), which the UI uses to drop it.
        if line is not None and not line.off and not line.offsets:
            text = None
        expected = {
            "line": text,
            "applied": apply(description, line)
            if line and text
            else apply(description, None),
            "removed": apply(description, None),
        }
        assert got == expected, description
