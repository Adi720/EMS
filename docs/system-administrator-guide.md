# EMS Seva — System administrator guide

For the person who installs and looks after EMS Seva: hosting, accounts with special rights,
settings, backups, updates and troubleshooting. Day-to-day use is in the
[coordinator manual](coordinator-user-manual.md).

## 1. Overview

- **Application:** Django 5.2 (Python 3.11+), server-rendered pages with Bootstrap; no separate
  front-end, no background workers.
- **Database:** SQLite (one file, `db.sqlite3`) is enough for this size (~130 Saints, ~40 users).
  PostgreSQL is also supported and adds a database-level guard against overlapping caller
  assignments.
- **Code:** GitHub repository; real contact data is **never** committed (`.env`, `*.sqlite3`,
  `*.xlsx`, `*.csv` are ignored).
- **Roles:** *System administrator* (`is_superuser`), *Coordinator* group, *Caller* group.

## 2. Accounts and roles

| Role | Created by | How |
|---|---|---|
| System administrator | You, on the server | `python manage.py createsuperuser` |
| Coordinator | System administrator | Django Admin → Users → Add → then add the **Coordinator** group |
| Caller | Coordinators (or you) | In the app: **Calling Team → Add caller**, or during the Excel import |
| Stall Lead | You, on the server | `python manage.py create_stall_lead` (creates `stall.sewa.admin`) |

**Create a coordinator:** your name (top right) → **Django Admin** → **Users** → **Add user** →
username and password → **Save** → fill in first/last name and email → **Groups: Coordinator** →
**Save**. Leave *Staff status* and *Superuser status* unticked. A person may have both Coordinator
and Caller groups.

Coordinators can only create and manage **Caller-only** accounts; they cannot grant coordinator or
admin rights, and cannot change coordinator or admin accounts. That is enforced on the server.

**Stall Lead login:** `python manage.py create_stall_lead` creates the shared login
`stall.sewa.admin` and prints its password **once** — share it privately with the stall team.
`python manage.py create_stall_lead --reset-password` gives it a new password. This login can only
add new Saints; each Saint it adds records the name of the person who added it.

**Forgot password** on the login page emails a reset link, so it only works for users with an
email address and once email sending is set up (section 6). Without that, reset passwords on the
Calling Team page (callers) or in Django Admin.

**Unlock a locked login** (5 failed attempts lock it for an hour): Django Admin → *Axes → Access
attempts* → delete the entry, or on the server:
`python manage.py axes_reset_username <username>`.

## 3. Hosting on PythonAnywhere (recommended)

The free plan is enough to start; the ~US$5 plan adds a custom domain, unrestricted outbound email
and no three-monthly renewal. Plan limits change — check their current pricing.

### 3.1 Install
In a PythonAnywhere **Bash console** (a private repo needs a GitHub fine-grained token with
*Contents: Read-only* as the password):
```bash
git clone https://github.com/Adi720/EMS.git SNM
cd ~/SNM
python3.11 -m venv .venv
.venv/bin/pip install -r requirements/base.txt
echo 'export DJANGO_SETTINGS_MODULE=config.settings.prod' >> ~/.bashrc && source ~/.bashrc
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(50))"   # copy the key
```

### 3.2 Settings (`~/SNM/.env`)
```
DJANGO_SECRET_KEY=<the long key>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=YOURNAME.pythonanywhere.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://YOURNAME.pythonanywhere.com
DJANGO_ADMIN_URL=<hard-to-guess-path>/
DATABASE_URL=sqlite:////home/YOURNAME/SNM/db.sqlite3
SITE_URL=https://YOURNAME.pythonanywhere.com
TIME_ZONE=Asia/Kolkata
```
Then:
```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
```

### 3.3 Web app
**Web** tab → *Add a new web app* → *Manual configuration* → *Python 3.11*:
- **Virtualenv:** `/home/YOURNAME/SNM/.venv`
- **WSGI file** (replace its contents):
  ```python
  import os, sys

  sys.path.insert(0, "/home/YOURNAME/SNM")
  os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.prod"
  from config.wsgi import application
  ```
- **Static files:** URL `/static/` → `/home/YOURNAME/SNM/staticfiles`
- **Force HTTPS:** on → **Reload**.

If the site keeps redirecting in a loop, add `DJANGO_SECURE_SSL_REDIRECT=False` to `.env` and
reload (Force HTTPS still keeps it on HTTPS).

### 3.4 Do the real import on the server
Data lives in the server's database; anything imported on a laptop stays on that laptop.

## 4. All settings

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | — (required) | Long random secret; never share or commit |
| `DJANGO_DEBUG` | `False` in production | Must be `False` on the server |
| `DJANGO_ALLOWED_HOSTS` | — | Site host name(s), comma-separated |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | — | `https://` + host name |
| `DJANGO_ADMIN_URL` | `admin/` | Path of Django Admin; use something hard to guess |
| `DATABASE_URL` | — (required) | `sqlite:////full/path/db.sqlite3` or `postgres://user:pass@host:5432/db` |
| `SITE_URL` | `http://127.0.0.1:8000` | Public address used in reminder emails |
| `TIME_ZONE` | `Asia/Kolkata` | Local time zone |
| `SESSION_IDLE_TIMEOUT_SECONDS` | `7200` | Logout after inactivity |
| `PHONE_DEFAULT_REGION` | `IN` | Country for mobile numbers without a country code |
| `ALLOCATION_CYCLE_MONTHS` | `3` | Suggested length of an allocation cycle |
| `ROTATION_REMINDER_DAYS` | `14` | Days before a cycle ends to show "time to rotate" |
| `IMPORT_MAX_UPLOAD_BYTES` / `IMPORT_MAX_ROWS` | 5 MB / 5000 | Workbook limits |
| `GENERATED_PASSWORD_LENGTH` | `10` | Passwords created for callers during import |
| `EMAIL_URL`, `DEFAULT_FROM_EMAIL` | console | Email sending (section 6) |
| `REMINDER_WEEKDAY` / `REMINDER_AUTO_START` | `5` (Saturday) / `True` | Reminder job (section 6) |
| `NEW_PERIOD_MONTHS` | `6` | Months after the stall date that a Saint stays **New** |
| `ON_HOLD_MONTHS` | `6` | Default next call date for **On Hold** |
| `PARTIALLY_ACTIVE_BELOW` / `PERFORMANCE_MONTHS` | `75` / `1` | A caller below this % of calls made over this many months is **Partially Active** |

After changing `.env`, click **Reload** on the Web tab.

## 5. Backups and restore

The whole database is **one file**: `~/SNM/db.sqlite3`.
- **Back up weekly:** PythonAnywhere **Files** tab → download `SNM/db.sqlite3`. Keep copies
  private — they contain names and phone numbers. Keep a few recent copies.
- **Restore:** upload the backup over `~/SNM/db.sqlite3`, then **Reload** the web app.
- Before any update (section 7), take a fresh backup.

## 6. Saturday reminder emails (optional)

`manage.py weekly_reminders` runs once a day. Every day it turns New Saints into Active ones after
6 months. On the reminder day (Saturday) it starts that week's calling (unless
`REMINDER_AUTO_START=False` or a coordinator chose **No Calling Sewa this week**) and emails each
caller who has an email address their link and number of Saints — once per congregation, so
running it twice is harmless. The same email settings are used for **Forgot password** and for
telling coordinators about new caller requests.

1. Create a Gmail account for the seva, turn on 2-Step Verification, create an **App password**.
2. Add to `.env` (write `@` in the username as `%40`):
   ```
   EMAIL_URL=smtp+tls://yourseva%40gmail.com:APPPASSWORD@smtp.gmail.com:587
   DEFAULT_FROM_EMAIL=EMS Seva <yourseva@gmail.com>
   ```
3. Test: `.venv/bin/python manage.py sendtestemail you@example.com` (changes nothing). On the free
   plan outbound email may be blocked — if so, use the WhatsApp button or upgrade.
4. **Tasks** tab → daily at **02:30 UTC** (08:00 India):
   ```
   cd ~/SNM && DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py weekly_reminders
   ```
5. Add callers' email addresses (Team → caller → Edit).

## 7. Updating the application

On your computer: commit and `git push`. Then on the server:
```bash
cd ~/SNM && git pull && .venv/bin/pip install -r requirements/base.txt \
  && .venv/bin/python manage.py migrate && .venv/bin/python manage.py collectstatic --noinput
```
then **Reload** on the Web tab. Migrations only add to the database; they never remove history.

## 8. Regular maintenance

| How often | Task |
|---|---|
| Weekly | Download a backup of `db.sqlite3` |
| Every 3 months (free plan) | Web tab → **Run until 3 months from today**; check the daily task has not expired |
| When people leave | Deactivate callers (Team) or coordinators (Django Admin → untick *Active*) — never delete; history is kept |
| Occasionally | Review the Audit log for unexpected activity |

## 9. Security checklist

- `DJANGO_DEBUG=False`, a long unique `DJANGO_SECRET_KEY`, a non-default `DJANGO_ADMIN_URL`.
- HTTPS on (Force HTTPS); cookies are secure in production settings.
- Give **System administrator** to as few people as possible; use the Coordinator group for
  coordinators.
- One login per person — no shared accounts.
- The workbook and backups contain personal data: keep them off shared drives and chats.
- Passwords and phone numbers are never written to the audit log.

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| "Bad Request (400)" | Host name missing from `DJANGO_ALLOWED_HOSTS` |
| "CSRF verification failed" on forms | `DJANGO_CSRF_TRUSTED_ORIGINS` must be `https://` + host |
| Pages without styling | Run `collectstatic` and check the static files mapping; reload |
| Redirect loop | `DJANGO_SECURE_SSL_REDIRECT=False` in `.env`, keep Force HTTPS on |
| Login locked | `manage.py axes_reset_username <name>` |
| Error page after an update | Check the Web tab **error log**; usually a missing `migrate` or `pip install` |
| Reminder emails not arriving | `sendtestemail`; check `EMAIL_URL`; free-plan email restrictions |

## 11. For developers

- Local setup, tests and checks: see the project [README](../README.md).
- `manage.py seed_demo_data --password …` fills an **empty development** database with made-up
  Saints and callers (refuses to run with `DEBUG=False` or if Saints exist).
- `scripts/docs_screenshots.py` regenerates the images in `docs/images` from a dev server running
  on demo data (requires Playwright, which is not a project dependency).
- Requirements and design decisions: [requirements.md](requirements.md); import details:
  [import-mapping.md](import-mapping.md).
