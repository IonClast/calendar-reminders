"""Unit tests for the #remind line parser."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.calendar_reminders.remind_line import (
    Offset,
    RemindLine,
    Unit,
    apply,
    parse,
    split,
)

OSLO = ZoneInfo("Europe/Oslo")
ALIASES = ("anna", "ben", "kitchen")


def m(n: int) -> Offset:
    return Offset(Unit.MINUTES, n)


def d(n: int) -> Offset:
    return Offset(Unit.DAYS, n)


def at(n: int, hh: int, mm: int) -> Offset:
    return Offset(Unit.DAYS_AT, n, time(hh, mm))


def oslo(*args: int) -> datetime:
    return datetime(*args, tzinfo=OSLO)


def elapsed(earlier: datetime, later: datetime) -> timedelta:
    """Real time between two instants (same-tzinfo subtraction is wall-clock)."""
    return later.astimezone(UTC) - earlier.astimezone(UTC)


# --- finding the line -------------------------------------------------------


@pytest.mark.parametrize(
    "description",
    [
        None,
        "",
        "   \n\n",
        "Bring cake",
        "#remind 1h\nBring cake",  # not the last line
        "#reminder 1h",  # a different word
        "Bring cake #remind 1h",  # not at the start of the line
    ],
)
def test_no_line(description: str | None) -> None:
    assert parse(description) is None


@pytest.mark.parametrize(
    "description",
    [
        "#remind 1h",
        "Bring cake\n#remind 1h",
        "Bring cake\r\n#remind 1h\r\n",
        "Bring cake\n#remind 1h\n\n   \n",
        "   #remind 1h   ",
        "#REMIND 1H",
        "#Remind 60m",
    ],
)
def test_line_found(description: str) -> None:
    assert parse(description) == RemindLine(offsets=(m(60),))


@pytest.mark.parametrize(
    "description",
    [
        "Notes<br>#remind 1h @ben",
        "Notes<br/>#remind 1h @ben",
        "<p>Notes</p><p>#remind&nbsp;1h @ben</p>",
        "<div>Notes</div><div>#remind 1h&nbsp;@ben</div>",
        "Notes\n<b>#remind 1h @ben</b>",
    ],
)
def test_google_html_description(description: str) -> None:
    """Descriptions edited on Google Calendar's web UI arrive as HTML."""
    assert parse(description) == RemindLine(offsets=(m(60),), devices=("ben",))


# --- offsets ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "offsets"),
    [
        ("0", (m(0),)),
        ("15", (m(15),)),  # 0.2.0: bare number = minutes
        ("15m", (m(15),)),
        ("2h", (m(120),)),
        ("1d", (d(1),)),
        ("1w", (d(7),)),
        ("1d@18:00", (at(1, 18, 0),)),
        ("0d@7:30", (at(0, 7, 30),)),
        ("30m 2h 1d", (m(30), m(120), d(1))),  # 0.2.0 tag
        ("60m 1h", (m(60),)),  # same duration only once
        ("7d 1w", (d(7),)),
        ("1h 1h 1h", (m(60),)),
    ],
)
def test_offsets(text: str, offsets: tuple[Offset, ...]) -> None:
    line = parse(f"#remind {text}")
    assert line is not None
    assert line.offsets == offsets
    assert line.unknown == ()
    assert line.active


@pytest.mark.parametrize(
    "token",
    [
        "1d@24:00",
        "1d@07:60",
        "1d@7:5",
        "1h@18:00",
        "1x",
        "-1h",
        "1.5h",
        "soon",
        "12345m",
        "@",
    ],
)
def test_unknown_tokens_are_reported(token: str) -> None:
    line = parse(f"#remind 1h {token}")
    assert line is not None
    assert line.offsets == (m(60),)
    assert line.unknown == (token,)


def test_no_offsets_is_not_active() -> None:
    line = parse("#remind @ben")
    assert line == RemindLine(devices=("ben",))
    assert not line.active
    assert parse("#remind") == RemindLine()


# --- devices, important, off ------------------------------------------------


def test_devices_lower_case_ordered_deduplicated() -> None:
    line = parse("#remind 1h @ANNA @ben @anna @Kitchen")
    assert line is not None
    assert line.devices == ("anna", "ben", "kitchen")


def test_unknown_alias_when_aliases_given() -> None:
    line = parse("#remind 1h @anna @bob", aliases=ALIASES)
    assert line is not None
    assert line.devices == ("anna",)
    assert line.unknown == ("@bob",)


def test_any_alias_when_aliases_not_given() -> None:
    line = parse("#remind 1h @bob")
    assert line is not None
    assert line.devices == ("bob",)


@pytest.mark.parametrize("text", ["30m !", "30m!", "! 30m", "30m @ben!"])
def test_important(text: str) -> None:
    line = parse(f"#remind {text}")
    assert line is not None
    assert line.important
    assert line.offsets == (m(30),)
    assert line.unknown == ()


@pytest.mark.parametrize("text", ["#remind off", "#remind OFF", "Notes\n#remind off\n"])
def test_off(text: str) -> None:
    line = parse(text)
    assert line == RemindLine(off=True)
    assert not line.active
    assert line.serialize() == "#remind off"


def test_off_ignores_and_reports_the_rest() -> None:
    line = parse("#remind off 1h @ben")
    assert line == RemindLine(off=True)
    assert line.unknown == ("1h", "@ben")


def test_unknown_not_part_of_equality() -> None:
    assert parse("#remind 1h junk") == parse("#remind 1h")


# --- serialize --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("30m 2h 1d", "#remind 1d 2h 30m"),
        ("15", "#remind 15m"),
        ("0", "#remind 0"),
        ("90m", "#remind 90m"),
        ("120m", "#remind 2h"),
        ("14d", "#remind 2w"),
        ("0d", "#remind 0d"),
        ("0d@7:30 1d@18:00", "#remind 1d@18:00 0d@07:30"),
        ("1d@18:00 1d@08:00", "#remind 1d@08:00 1d@18:00"),
        ("1h 1w 0 2d", "#remind 1w 2d 1h 0"),
        ("1h @ben @anna !", "#remind 1h @ben @anna !"),
        ("! @kitchen 5m", "#remind 5m @kitchen !"),
    ],
)
def test_serialize_canonical(text: str, canonical: str) -> None:
    line = parse(f"#remind {text}")
    assert line is not None
    assert line.serialize() == canonical


@pytest.mark.parametrize(
    "line",
    [
        RemindLine(offsets=(d(1), m(60)), devices=("anna", "ben")),
        RemindLine(
            offsets=(at(1, 18, 0), at(0, 7, 30)), devices=("kitchen",), important=True
        ),
        RemindLine(offsets=(m(0), m(90), d(14))),
        RemindLine(off=True),
    ],
)
def test_round_trip(line: RemindLine) -> None:
    parsed = parse(line.serialize(), aliases=ALIASES)
    assert parsed is not None
    assert set(parsed.offsets) == set(line.offsets)
    assert (parsed.devices, parsed.important, parsed.off) == (
        line.devices,
        line.important,
        line.off,
    )


# --- split / apply ----------------------------------------------------------

LINE = RemindLine(offsets=(m(60),), devices=("ben",))


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        (None, "#remind 1h @ben"),
        ("", "#remind 1h @ben"),
        ("Bring cake", "Bring cake\n#remind 1h @ben"),
        ("Bring cake\n\n", "Bring cake\n#remind 1h @ben"),
        ("Bring cake\n#remind 2h", "Bring cake\n#remind 1h @ben"),
        ("Bring cake\n#remind 2h\n \n", "Bring cake\n#remind 1h @ben"),
        ("#remind 2h", "#remind 1h @ben"),
        ("Line 1\n\nLine 3\n#remind off", "Line 1\n\nLine 3\n#remind 1h @ben"),
        # A #remind that isn't the last line is plain text and stays.
        ("#remind 2h\nBring cake", "#remind 2h\nBring cake\n#remind 1h @ben"),
    ],
)
def test_apply_sets_line(description: str | None, expected: str) -> None:
    assert apply(description, LINE) == expected
    assert parse(expected) == LINE


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        (None, ""),
        ("Bring cake", "Bring cake"),
        ("Bring cake\n#remind 2h", "Bring cake"),
        ("Bring cake\n\n#remind 2h\n", "Bring cake"),
        ("#remind 2h", ""),
    ],
)
def test_apply_none_removes_line(description: str | None, expected: str) -> None:
    assert apply(description, None) == expected


def test_split() -> None:
    assert split("Bring cake\n#remind 2h @ben ") == ("Bring cake", "#remind 2h @ben")
    assert split("Bring cake\n") == ("Bring cake", None)
    assert split(None) == ("", None)


# --- trigger times ----------------------------------------------------------


@pytest.mark.parametrize(
    ("offset", "start", "expected"),
    [
        (m(0), oslo(2026, 11, 2, 10, 0), oslo(2026, 11, 2, 10, 0)),
        (m(30), oslo(2026, 11, 2, 10, 0), oslo(2026, 11, 2, 9, 30)),
        (m(90), oslo(2026, 11, 2, 0, 30), oslo(2026, 11, 1, 23, 0)),
        (d(1), oslo(2026, 11, 2, 10, 0), oslo(2026, 11, 1, 10, 0)),
        (d(7), oslo(2026, 11, 2, 10, 0), oslo(2026, 10, 26, 10, 0)),
        (d(28), oslo(2026, 11, 30, 10, 0), oslo(2026, 11, 2, 10, 0)),  # 4 weeks
        # d@ on a timed event: n days before the event's date, at that time.
        (at(1, 18, 0), oslo(2026, 11, 2, 14, 0), oslo(2026, 11, 1, 18, 0)),
    ],
)
def test_trigger_timed(offset: Offset, start: datetime, expected: datetime) -> None:
    assert offset.trigger_time(start, OSLO) == expected


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (at(1, 18, 0), oslo(2026, 11, 1, 18, 0)),
        (at(0, 7, 30), oslo(2026, 11, 2, 7, 30)),
        (m(0), oslo(2026, 11, 2, 0, 0)),
        (m(60), oslo(2026, 11, 1, 23, 0)),
        (d(1), oslo(2026, 11, 1, 0, 0)),
    ],
)
def test_trigger_all_day(offset: Offset, expected: datetime) -> None:
    """All-day events start at local midnight."""
    assert offset.trigger_time(date(2026, 11, 2), OSLO) == expected


def test_hours_are_absolute_across_spring_forward() -> None:
    # 29 Mar 2026: 02:00 CET -> 03:00 CEST. 03:30 CEST minus 2 h is 00:30 CET.
    fire = m(120).trigger_time(oslo(2026, 3, 29, 3, 30), OSLO)
    assert fire == oslo(2026, 3, 29, 0, 30)
    assert elapsed(fire, oslo(2026, 3, 29, 3, 30)) == timedelta(hours=2)


def test_days_keep_wall_clock_across_spring_forward() -> None:
    start = oslo(2026, 3, 29, 10, 0)
    fire = d(1).trigger_time(start, OSLO)
    assert (fire.day, fire.hour, fire.minute) == (28, 10, 0)
    assert elapsed(fire, start) == timedelta(hours=23)


def test_days_keep_wall_clock_across_fall_back() -> None:
    # 25 Oct 2026: 03:00 CEST -> 02:00 CET.
    start = oslo(2026, 10, 25, 10, 0)
    fire = d(1).trigger_time(start, OSLO)
    assert (fire.day, fire.hour, fire.minute) == (24, 10, 0)
    assert elapsed(fire, start) == timedelta(hours=25)


def test_fixed_time_in_dst_gap_moves_forward() -> None:
    # 02:30 on 29 Mar 2026 doesn't exist in Oslo; it becomes 03:30 CEST.
    fire = at(1, 2, 30).trigger_time(date(2026, 3, 30), OSLO)
    assert fire.astimezone(UTC) == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    assert (fire.hour, fire.minute) == (3, 30)


def test_fixed_time_in_repeated_hour_uses_first_pass() -> None:
    # 02:30 on 25 Oct 2026 happens twice in Oslo; the CEST one comes first.
    fire = at(1, 2, 30).trigger_time(date(2026, 10, 26), OSLO)
    assert fire.astimezone(UTC) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)


def test_start_in_other_timezone_is_converted() -> None:
    start = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)  # 10:00 in Oslo
    fire = d(1).trigger_time(start, OSLO)
    assert fire == oslo(2026, 11, 1, 10, 0)
    assert fire.tzinfo is OSLO


def test_naive_start_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        m(10).trigger_time(datetime(2026, 11, 2, 10, 0), OSLO)
