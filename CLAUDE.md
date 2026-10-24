# calendar_reminders — notes for Claude Code

Home Assistant custom integration (HACS), domain `calendar_reminders`. Work happens on branch `v1`; `main` is
fast-forwarded to it so HACS (which installs the default branch) can pick it up. Private, machine-specific notes are
in `CLAUDE.local.md` (git-ignored), if present.

- **Versioning:** an incremental change bumps the last number (0.3.0 → 0.3.1); a major change bumps the middle number
  (0.3.x → 0.4.0). Bump `manifest.json` `version` with every change pushed for HACS.
- **Behaviour:** the README is the user-facing description of the `#remind` line, recipients and notifications.
- **Target:** HA 2026.10.2, frontend 20260930.4, Python 3.14. `hacs.json` minimum is 2026.10.0.
- **Layout:** `custom_components/calendar_reminders/` (brand images in `brand/`, frontend JS in `www/`), `tests/`.

## Dev loop
- `.venv` (git-ignored) is a Python 3.14 venv from `requirements_test.txt`
  (`pytest-homeassistant-custom-component` 0.13.373 = homeassistant 2026.10.2, `ical` 14.3.0, `ruff`).
  Create it with `uv venv --python 3.14 .venv` and `uv pip install --python .venv/Scripts/python.exe -r requirements_test.txt`.
- Lint: `ruff check .` and `ruff format --check .`
- Tests: **don't run natively on Windows.** `homeassistant.runner` imports `fcntl`, which is Unix-only, so the pytest
  plugin fails on import. Run them in CI (`.github/workflows/ci.yml`), on Linux, or under WSL with a Linux venv.
- Tests that set up `local_calendar` must point `hass.config.config_dir` at `tmp_path` and create `.storage`
  (the `calendar` fixture in `tests/conftest.py` does this; helpers are in `tests/common.py`).
- `hass_frontend` (a 110 MB wheel) isn't installed for tests: the autouse `frontend_stub` fixture marks `frontend` as
  loaded and patches `add_extra_js_url`.
- Config flow schemas use `probatio` (HA 2026.10 replaced voluptuous with it; the API is the same).
- Files are LF (`.gitattributes`). Don't commit CRLF.

## Rules
- This repository is **public**. Use generic examples only (`@anna`, `@ben`, `@kitchen`, "Main Street Clinic",
  "Family calendar"): no real names, devices, calendars, places, domains or local paths.
- Never write tokens, passwords, webhook IDs, shared secrets or e-mail addresses into the repository.
- Don't push, and don't change a live Home Assistant, without the owner's explicit OK.
