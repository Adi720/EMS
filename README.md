# EMS Seva Management System

Django application for EMS Calling Seva: contacts, long-term caller allocations with
three-monthly rotation, weekly calling sessions and outcomes, dashboards, reports, exports and
the initial workbook import.

- Requirements and implementation decisions: [docs/requirements.md](docs/requirements.md)
- Workbook import mapping: [docs/import-mapping.md](docs/import-mapping.md)
- Quick start: [docs/user-guide.md](docs/user-guide.md)
- Manuals: [coordinator](docs/coordinator-user-manual.md) · [caller](docs/caller-user-manual.md) ·
  [system administrator](docs/system-administrator-guide.md) · [feature catalogue](docs/feature-catalogue.md)

In the screens, each weekly Sunday EMS is called an **EMS Congregation**, shown as e.g.
"EMS Congregation (1/11/26)". In the code it is the `EmsSession` model.

> **Data rule:** never put real contact data (e.g. `2026 EMS DATA.xlsx`) under version control.
> `*.xlsx` and `*.csv` are git-ignored. Development and tests use synthetic data only.

## What it does

| Role | Main screens |
|---|---|
| Caller | **My calls**: the session's allocated contacts, pending first, tap-to-call, one-tap outcome (Yes / Not Possible / Will Try / Call Not Connected), notes and call-back time, own progress |
| Coordinator | **Dashboard** (live progress by caller, session history), **Contacts** (search, lifecycle, history, export), **Allocations** (assign, move, swap, rotate with preview; cycles), **Sessions** (open/close, weekly report, exports), **Monthly** report, **Import**, **Audit** |
| System admin | Everything a coordinator can do, plus Django Admin for users and roles |

## Local setup on Windows (no Docker)

Requires Python 3.11+. PostgreSQL is recommended (and required to verify the
PostgreSQL-only allocation overlap constraint); SQLite works for quick development.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
Copy-Item .env.example .env
# edit .env: set DJANGO_SECRET_KEY and DATABASE_URL
```

### Database option A — your PostgreSQL server

In `psql` as the `postgres` superuser:

```sql
CREATE ROLE ems_seva LOGIN PASSWORD 'choose-a-local-password' CREATEDB;
CREATE DATABASE ems_seva OWNER ems_seva;
```

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost
```

`.env`: `DATABASE_URL=postgres://ems_seva:choose-a-local-password@localhost:5432/ems_seva`.
`CREATEDB` lets the test runner create `test_ems_seva`. The migration that adds the overlap
constraint runs `CREATE EXTENSION IF NOT EXISTS btree_gist` (a trusted extension, allowed for the
database owner on PostgreSQL 13+).

### Database option B — SQLite (development only)

`.env`: `DATABASE_URL=sqlite:///db.sqlite3`. Everything works except the PostgreSQL-only
overlap constraint (its test is skipped).

### Run

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py seed_demo_users --password "<a local demo password>"
.\.venv\Scripts\python.exe manage.py runserver
```

Open http://127.0.0.1:8000/. Demo users (synthetic, DEBUG only): `demo.coordinator`,
`demo.caller1`, `demo.caller2`, `demo.both`.

To try the import with fake data:

```powershell
.\.venv\Scripts\python.exe manage.py generate_synthetic_workbook $env:TEMP\synthetic-ems.xlsx
```

The command prints the four synthetic caller names; create users with those first and last
names (Django Admin → Users, Caller group) to see automatic caller matching.

## Tests and checks

```powershell
.\.venv\Scripts\python.exe -m pytest                     # uses DATABASE_URL or TEST_DATABASE_URL
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
$env:DJANGO_SETTINGS_MODULE="config.settings.prod"; $env:DJANGO_ALLOWED_HOSTS="ems.example.org"
.\.venv\Scripts\python.exe manage.py check --deploy --fail-level WARNING
```

Run the tests against PostgreSQL before deploying:
`$env:TEST_DATABASE_URL="postgres://ems_seva:...@localhost:5432/ems_seva"; .\.venv\Scripts\python.exe -m pytest`.

## Manual test (one coordinator, one caller)

1. Log in as `demo.coordinator` → **Contacts → Add contact**: name, phone `98765 43210`, area,
   registration date; *Allocate to* `Demo Caller One`, allocation start today. Save.
2. **Dashboard → Start calling for EMS Congregation (d/m/yy)** (the coming Sunday) — the
   message reports 1 contact added to the call lists.
3. In a private window, log in as `demo.caller1` → **My calls**: the contact is listed as
   Pending with a call button. Tap **Will Try**, then open the contact and record **Yes** with a note.
4. Back as coordinator → **Dashboard**: Assigned 1, Completed 1, Connected 1, Yes 1, Will Try 0,
   Unknown 0. Open the congregation (Details &amp; exports) → **Export → Per-caller summary (Excel)**.
5. As coordinator, open the contact → **Change status** → *Do not call*. As the caller, reload:
   the phone number is hidden and no outcome buttons are shown; the earlier attempt is kept.
6. Try `http://127.0.0.1:8000/contacts/` as the caller → *Access denied*.
7. **Audit** (coordinator) lists each of these actions.

## Saturday reminder emails (optional)

`manage.py weekly_reminders` is meant to run **once a day** from the host's scheduler. On the
reminder day (Saturday, `REMINDER_WEEKDAY=5`) it starts that week's calling — unless
`REMINDER_AUTO_START=False` — and emails every caller who has an email address their link and
contact count. It never emails the same caller twice for one congregation, so running it more
than once is harmless. On other days it does nothing.

1. Set `EMAIL_URL`, `DEFAULT_FROM_EMAIL` and `SITE_URL` (see `.env.example`). Without
   `EMAIL_URL`, emails are only printed to the console.
2. Add callers' email addresses in Django Admin → Users.
3. Try it: `manage.py weekly_reminders --force` (or `--date 2026-10-31` to pretend it is Saturday).
4. Schedule it daily, e.g. on PythonAnywhere → **Tasks** → daily at 02:30 UTC (08:00 IST):
   `cd ~/SNM && DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py weekly_reminders`

The coordinator dashboard also offers **Share reminder on WhatsApp** (a `wa.me` link with the
message filled in) once calling is open — no setup needed.

## Roles

| Role | How it is granted |
|---|---|
| Caller | Django Admin → Users → add to the `Caller` group |
| Coordinator | Add to the `Coordinator` group |
| System administrator | `is_staff` + `is_superuser` (has every coordinator capability) |

Every page requires login; role pages return 403 and other callers' records 404. To unlock an
account after repeated failed logins: Django Admin → Axes → Access attempts, or
`manage.py axes_reset_username <username>`.

## Configuration

All settings come from environment variables (see `.env.example`). Settings modules:
`config.settings.dev` (default for `manage.py`), `config.settings.test` (pytest),
`config.settings.prod` (WSGI; requires HTTPS, secure cookies, HSTS).

Production must set `DJANGO_SECRET_KEY`, `DATABASE_URL` (PostgreSQL), `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CSRF_TRUSTED_ORIGINS` and a non-default `DJANGO_ADMIN_URL`, then run
`manage.py migrate` and `manage.py collectstatic`, and serve with
`gunicorn config.wsgi:application` behind an HTTPS reverse proxy.

The `Dockerfile`, `docker-compose.yml` and `.github/workflows/ci.yml` are provided but have
**not** been executed (no Docker or CI available during development).
