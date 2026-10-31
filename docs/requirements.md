# EMS Seva Management System — Requirements (v3)

Status: requirements consolidated 2026-10-29; MVP implemented 2026-10-30 (see §15 for the
implementation decisions and defaults chosen, and §14 for what still needs the business).

**Labels**

| Label | Meaning |
|---|---|
| **[C]** | Confirmed by the business |
| **[D]** | Recommended default accepted by the business (treated as confirmed) |
| **[A]** | Assumption — proceed with it unless the business objects |
| **[P]** | Design proposal from the technical lead |

---

## 0. Decision log

| # | Decision | Label |
|---|---|---|
| 1 | Contacts are allocated to a caller long-term (~3 months), not weekly | [C] |
| 2 | Rotation every ~3 months; supports whole-list swaps **and** selective redistribution of all or selected contacts; preview before apply; effective date + reason recorded; full history; audited | [C] |
| 3 | Individual reassignment of a single contact is supported | [C] |
| 4 | Contacts can be made temporarily unavailable / inactive with reason and date, removed from calling, history retained, and reactivated | [C] |
| 5 | "Moved away / unavailable" is distinct from "requested not to be called" | [C] |
| 6 | **An attempted call is completed work, whether or not it connects** | [C] |
| 7 | Outcomes: `Yes`, `Not Possible`, `Will Try`, `Call Not Connected` | [C] |
| 8 | `Will Try` is **not** a confirmed intention | [C] |
| 9 | Multiple attempts per contact per session are kept; the latest attempt determines the current outcome | [C] |
| 10 | Intention is distinct from actual attendance; actual attendance is **not** an MVP feature | [C] |
| 11 | Required contact fields: Name, Phone, Area, Registration date | [C] |
| 12 | Workbook `DATE` (sheet `EMS STALL SEWA`) = date the contact was collected at the stall → `registration_date` | [C] |
| 13 | MVP import = current contact details + existing caller allocations only; historical weekly columns, outcomes and attendance are **not** migrated without separate approval | [C] |
| 14 | `SEWA CONDUCTED BY` and `CALLING CO-ORDINATER` are not assumed to mean the same thing; roles validated during mapping | [C] |
| 15 | Area is free text in the MVP; existing values must not be lost or altered on import | [D] |
| 16 | Initial allocation effective date = current cycle start date, confirmed by the coordinator during import; never the registration date | [D] |
| 17 | Mid-week reassignment moves **unattempted** tasks to the new caller; attempted tasks stay credited to the original caller | [D] |
| 18 | Inactive / Do Not Call withdraws **unattempted** tasks from the open session; attempted tasks and history are preserved | [D] |
| 19 | Synthetic data only during development; no real contact data in source control | [C] |

---

## 1. Scope

A secure, mobile-friendly web application replacing the Excel workbook used for
EMS Calling Seva: contacts collected at the stall are allocated long-term to callers,
who call them before each Sunday EMS session and record outcomes; coordinators
manage contacts, allocations and sessions, monitor progress and produce reports.

Expected users: 30–40 [C].

**MVP (release 1):** authentication & roles, contacts & lifecycle, allocations &
rotation, initial workbook import, sessions & calling workflow, dashboards,
weekly/monthly reports, CSV/XLSX export, audit trail.

**Out of MVP:** actual attendance tracking [C], historical weekly outcome import [C],
reminders [C], configurable outcome lists [P].

## 2. Roles

| Role | Description | Label |
|---|---|---|
| Caller | Calls their allocated contacts and records outcomes | [C] |
| Coordinator | Manages contacts, sessions, allocations, monitors, reports, exports | [C] |
| System administrator | Manages accounts, settings, Django Admin | [C] |

- A user may hold more than one role (e.g. a coordinator who also calls) [A].
- Individual accounts only; no shared logins [A].
- Accounts are created by the system administrator; no self-registration [A].
- All coordinators can see and manage all callers and contacts in the MVP [A]
  (the workbook suggests callers are grouped under coordinators — see §14 A-3).

## 3. Functional requirements

### FR-1 Authentication & authorization
| ID | Requirement | Label |
|---|---|---|
| FR-1.1 | Username + password login; logout via POST | [C]/[P] |
| FR-1.2 | Every page requires login by default (deny-by-default) | [P] |
| FR-1.3 | Role checks enforced server-side on every view, queryset and export | [C] |
| FR-1.4 | Records outside a user's scope return 404 (not revealed) | [P] |
| FR-1.5 | Login lockout after 5 failed attempts per username+IP for 1 hour | [P] |
| FR-1.6 | Sessions expire after 2 hours of inactivity | [P] |

### FR-2 Contacts
| ID | Requirement | Label |
|---|---|---|
| FR-2.1 | Required: full name, phone, area, registration date | [C] |
| FR-2.2 | Optional: secondary phone, qualification, collected-by name, notes | [A] — only fields present in the existing workbook; no new mandatory personal data |
| FR-2.3 | Phone numbers validated and normalised to E.164; default region India (+91) | [A] |
| FR-2.4 | Duplicate warning on same normalised phone (shared family phones allowed after confirmation) | [P] |
| FR-2.5 | Area stored as entered (trimmed only); no automatic correction | [D] |
| FR-2.6 | Contacts are never hard-deleted while history exists | [C] |
| FR-2.7 | Coordinator can merge duplicates, preserving all history | [P] |

### FR-3 Contact lifecycle — see §6.

### FR-4 EMS sessions
| ID | Requirement | Label |
|---|---|---|
| FR-4.1 | Coordinator creates a session with a session date | [C] |
| FR-4.2 | Lifecycle: Draft → Open for calling → Closed | [P] |
| FR-4.3 | Creating new sessions never alters past sessions' data | [C] |
| FR-4.4 | One session per date per venue | [A] |

### FR-5 Allocation — see §5.

### FR-6 Calling — see §7.

### FR-7 Dashboards
- Caller: upcoming session, my pending contacts first, my completed/connected counts [C].
- Coordinator: per-caller progress for the selected session, unallocated active contacts,
  temporarily-unavailable contacts due for review [C]/[P].

### FR-8 Reports & exports
- Weekly (per session) and monthly reports using the metrics in §8 [C].
- CSV and XLSX export; coordinators only; fixed approved column sets; every export audited;
  spreadsheet formula injection neutralised [C]/[P].

### FR-9 Initial import — see §10 and `docs/import-mapping.md`.

### FR-10 Audit
- History of every change to contacts, allocations, call attempts and status; log of logins,
  exports, imports and rotations (who, when, what) [C]/[P].

---

## 4. Data model [P]

```
User ──< Allocation >── Contact ──< ContactStatusChange
            │              │
     AllocationCycle       │
     AllocationOperation   │
                           │
EmsSession ──< CallTask >──┘
                  └──< CallAttempt

ImportBatch ──< ImportRow ──> Contact / Allocation
CallerAlias ──> User
[post-MVP] Attendance (contact × session)
```

| Entity | Purpose | Key fields / constraints |
|---|---|---|
| `accounts.User` | Custom user (Phase 1) | Django `AbstractUser`; roles via groups `Caller`, `Coordinator`; admins via `is_staff`/`is_superuser` |
| `contacts.Contact` | A person | `full_name`, `phone_primary` (E.164, indexed, not unique), `phone_secondary`, `area` (free text), `registration_date`, `qualification`, `collected_by_name`, `notes`, `status`, `status_since`, `merged_into`, `legacy_data` (JSON) |
| `contacts.ContactStatusChange` | Append-only lifecycle history | `from_status`, `to_status`, `reason_category`, `reason_text`, `effective_date`, `review_date`, `changed_by`, `changed_at` |
| `allocations.AllocationCycle` | ~3-month rotation period | `name`, `start_date`, `planned_end_date`, `status` |
| `allocations.Allocation` | Who is responsible for a contact over a date range | `contact`, `caller`, `effective_from`, `effective_to` (null = open), `cycle`, `operation`, `change_type`, `reason`, `created_by`. **One open allocation per contact; no overlapping ranges** (PostgreSQL exclusion constraint). Rows never edited in place |
| `allocations.AllocationOperation` | One bulk swap / redistribution / individual reassignment | `kind`, `effective_date`, `reason`, `performed_by`, `performed_at`, `summary` (JSON) |
| `ems_sessions.EmsSession` | A Sunday EMS session | `session_date`, `title`, `venue`, `status` |
| `calling.CallTask` | One contact × one session work item | `session`, `contact` (unique together), `caller` (snapshot), `status` (Open/Withdrawn), `withdrawn_reason`, cached `latest_outcome`, `attempt_count`, `last_attempt_at` |
| `calling.CallAttempt` | Append-only attempt log | `task`, `outcome`, `notes`, `attempted_at`, `recorded_by` |
| `imports.ImportBatch` / `ImportRow` | Staged import | file name, SHA-256 hash, mapping, status, counts; per row: sheet, row number, raw values (JSON), normalised values, issues, resolution |
| `imports.CallerAlias` | Remembers workbook name → user | `alias` (normalised, unique), `user` |

## 5. Allocation & rotation workflow

**Rules**
- A contact has at most one open allocation; history is the sequence of allocation rows [C].
- Every change records previous caller, new caller, effective date, reason and who made it [C].
- Changes are applied atomically and audited; a mistake is undone by a reversing operation,
  never by deleting rows [C]/[P].

**Individual reassignment [C]** — coordinator picks contact → new caller, effective date
(default today), reason → system closes the current allocation the day before and opens a new one.

**Rotation [C]** — coordinator creates/selects the next cycle, then builds a change set with:
- *Swap lists*: all of caller A's contacts ↔ all of caller B's contacts;
- *Move all*: all of A's contacts → B (or spread across several callers);
- *Move selected*: chosen contacts (filterable by area/caller) → a caller.

A **preview** lists every contact whose caller changes (old → new), resulting counts per caller,
and warnings (caller left with 0 contacts, inactive caller, non-active contacts). **Apply**
records one `AllocationOperation` with effective date and reason. Unchanged contacts keep their
open allocation [P].

**Effect on an open session [D]**
- Unattempted task → moves to the new caller.
- Attempted task → stays credited to the original caller.

## 6. Contact lifecycle

| Status | Meaning | In calling list | Allocation | Reactivation |
|---|---|---|---|---|
| Active | Normal | Yes | Open | — |
| Temporarily unavailable | Away for a period; optional review date | No | Kept open [A] (returns to same caller) | Coordinator |
| Inactive | Moved away / no longer able to attend | No | Closed on effective date [A] | Coordinator assigns a caller |
| Do Not Call | Person asked not to be contacted [C] | No | Closed | Coordinator only, mandatory note confirming consent [P] |
| ~~Merged~~ | Not implemented: duplicates are flagged (create/edit/import) and never merged automatically | — | — | — |

- Each change records reason category, reason text, effective date and who made it [C].
- Nothing is deleted; tasks, attempts, allocations and status history remain [C].
- Leaving Active withdraws **unattempted** tasks in open sessions; attempted tasks remain [D].
- Do Not Call additionally hides the phone number from caller views and excludes the contact
  from exports by default [P].

## 7. Calling workflow

1. Coordinator opens a session for calling → a `CallTask` is created for each Active contact
   with an open allocation on the session date, assigned to that caller [P].
2. Contacts allocated/reactivated while the session is open get a task automatically [P].
3. Caller sees **their own** tasks only, pending first, with tap-to-call [C]/[P].
4. Caller records an attempt with one outcome and optional notes; may record further attempts;
   the latest attempt is the current outcome [C].

| Outcome | Connected | Intention category | Completed |
|---|---|---|---|
| Yes | Yes | **Confirmed** | Yes |
| Not Possible | Yes | Not possible | Yes |
| Will Try | Yes | **Unsure (not confirmed)** | Yes |
| Call Not Connected | No | Unknown | Yes |
| *(no attempt)* | — | Unknown | No |

Outcomes are code-defined choices mapped to these categories [P]. "Call back later" is not an
MVP outcome; an optional free-text note covers it [A].

## 8. Metrics

Unit: one non-withdrawn `CallTask` (contact × session). Current outcome = latest attempt.

| Metric | Definition | Label |
|---|---|---|
| Assigned | Non-withdrawn tasks in the session | [C] |
| **Completed (attempted)** | Tasks with ≥1 attempt, any outcome | [C] |
| Not yet attempted | Assigned − Completed | [C] |
| Connected | Current outcome ∈ {Yes, Not Possible, Will Try} | [C]/[P] |
| Confirmed | Current outcome = Yes | [C] |
| Not possible | Current outcome = Not Possible | [C] |
| Will try | Current outcome = Will Try (reported separately, never as confirmed) | [C] |
| Intention unknown | Not attempted, or current outcome = Call Not Connected | [C]/[P] |
| Completion rate | Completed ÷ Assigned | [P] |
| Connection rate | Connected ÷ Completed | [P] |
| Actual attendance | Not recorded in MVP; shown as "not recorded" | [C] |

**Integrity rule:** Confirmed + Not possible + Will try + Unknown = Assigned (per caller, per
session). Enforced by tests.

**Example [C]:** 5 assigned, 5 attempted → Completed 5 (100%) regardless of outcomes.

**Monthly report [A]:** sessions grouped by the calendar month of the session date; metrics
summed across sessions; per-session trend; unique contacts confirmed shown separately.

**Breakdowns:** per caller, per area, overall.

## 9. Permission matrix

| Capability | Caller | Coordinator | Sys admin |
|---|---|---|---|
| Log in, change own password | ✅ | ✅ | ✅ |
| View own call tasks & limited contact details (name, phone, area, own notes) | ✅ | ✅ if also Caller | ✅ if also Caller |
| View other callers' tasks | ❌ | ✅ | ✅ |
| View / search all contacts | ❌ | ✅ | ✅ |
| Create / edit / change status / merge contacts | ❌ | ✅ | ✅ |
| Record attempt on own task | ✅ | ✅ if also Caller | ✅ if also Caller |
| Record attempt on another caller's task | ❌ | ✅ (audited) | ✅ |
| Manage sessions | ❌ | ✅ | ✅ |
| Allocate / reassign / rotate | ❌ | ✅ | ✅ |
| Dashboards & reports (all callers) | ❌ | ✅ | ✅ |
| Export CSV/XLSX | ❌ | ✅ (audited) | ✅ |
| Import workbook | ❌ | ✅ | ✅ |
| Manage users and roles | ❌ | ❌ | ✅ |
| Django Admin | ❌ | ❌ | ✅ |

## 10. Initial import

Full mapping and validation rules: [`docs/import-mapping.md`](import-mapping.md).

Summary: upload XLSX/CSV → map columns → stage rows → validate (required fields, phone,
duplicates, caller names vs users) → preview & coordinator resolution → confirm cycle start
date → atomic commit of contacts + initial allocations → import summary with per-caller
reconciliation. Repeat-safe; raw rows retained; historical weekly columns kept only in staging,
not migrated [C].

## 11. Non-functional & security requirements

- Server-side authorization; deny-by-default login; 404 for out-of-scope records [C]/[P].
- CSRF protection on all state-changing requests; no state change via GET [C].
- Input validation on all forms and imports [C].
- Secrets and real data out of source control; environment-based configuration [C].
- HTTPS, secure cookies, HSTS, clickjacking protection in production [P].
- Login throttling (django-axes), strong password validation, inactivity timeout [P].
- Export formula-injection protection; exports audited [P].
- Daily encrypted database backups with tested restore [P].
- Mobile-first Bootstrap UI usable on low-end Android phones [C]/[P].

## 12. Phased plan

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: project, settings, PostgreSQL config, custom user, roles, login, base UI, tests | Done |
| 2 | Contacts & lifecycle | Done |
| 3 | Allocations, cycles, rotation, history | Done |
| 4 | Initial import | Done; caller column confirmed (B-1). Real import is the coordinator's next step |
| 5 | Sessions & calling workflow | Done |
| 6 | Dashboards, reports, exports | Done |
| 7 | Hardening, deployment, real import, UAT | Security review done; deployment, real import and UAT outstanding |
| Later | Attendance, historical outcome import, reminders | Separate approval |

## 13. Testing strategy

pytest + pytest-django; tests against PostgreSQL in CI. Mandatory suites: role/URL access
matrix, caller isolation (IDOR) tests per caller-facing view, database constraint tests,
lifecycle and allocation-history tests, metric fixtures with hand-computed expected values,
import tests on a synthetic workbook (duplicates, bad phones, caller-name variants,
re-import), export tests (columns, formula escaping, role denial), `check --deploy`.
Results are only reported from real runs.

## 14. Open questions

### Resolved (2026-10-31)

- **B-1 Per-contact caller column — confirmed [C].** In `EMS STALL SEWA`, `CALLING CO-ORDINATER`
  holds the Saint who has been given the seva of calling that contact, i.e. the allocated
  **caller**. The importer maps it to `Allocation.caller`. The commit screen still asks for an
  explicit tick as a last safety check, and the automatic "looks like coordinators / stall seva"
  warnings remain.
- **B-2 `2026 Calling Sewa status` — optional [C].** The sheet is not reliably maintained, so it
  is ignored unless the coordinator ticks "compare caller counts" at upload; even then it is only
  a cross-check and never changes data.

No questions block the real import. Remaining step: upload the real workbook, review the preview
(rows needing attention, caller logins to create), then import.

### Assumptions to confirm (work proceeds with these)

- **A-1** Phone numbers default to India (+91); time zone Asia/Kolkata; text dates read as DD/MM/YYYY.
- **A-2** `QUALIFICATION` is kept as an optional contact field; `SEWA CONDUCTED BY` is stored as
  free-text "collected by" (stall seva member), not mapped to user accounts.
- **A-3** All coordinators see all callers and contacts (no per-coordinator team restriction).
  The caller → coordinator grouping from the workbook can be recorded for reporting later.
- **A-4** A user may hold Caller and Coordinator roles together.
- **A-5** Temporarily unavailable keeps the allocation; Inactive/Do Not Call closes it.

### Non-blocking (before go-live)

- **N-1** Actual-attendance coordinator workflow.
- **N-2** Consent at the stall, retention period, and whether Do Not Call requires data deletion.
- **N-3** Report recipients and expected format.
- **N-4** Hosting budget, domain, technical maintainer, data residency.
- **N-5** Whether any contacts are under 18.
- **N-6** Interface language(s).

---

## 15. Implementation decisions and defaults (2026-10-30)

Routine decisions taken during implementation. All are **[A]** unless marked; change requests welcome.

### Data model as built
| Area | Decision |
|---|---|
| Apps | `contacts`, `allocations`, `calling` (holds `EmsSession`, `CallTask`, `CallAttempt`), `reports`, `imports`, `audit`, plus Phase 1 `accounts`, `core` |
| Allocation dates | `effective_to` is **exclusive** (the date the next allocation took effect). History shows the inclusive last day. A same-day correction produces a zero-length row, kept for history |
| Allocation integrity | One open allocation per contact (DB partial unique index, all databases); end ≥ start (DB check); **no overlapping ranges** (PostgreSQL `EXCLUDE USING gist`, migration `allocations.0002`; skipped on SQLite); changes cannot be backdated before the current allocation's start |
| Inactive / Do not call | Cannot be allocated (bulk or individual) until reactivated |
| Call tasks | Created when a session is opened (and by "Refresh tasks"); one per contact per session (DB unique). Attempted tasks can never be withdrawn (DB check). `latest_outcome` is cached on the task and kept consistent by a DB check |
| Attempts | Append-only. Mistakes are corrected by recording another attempt (latest wins); there is no edit/delete |
| Sessions | Draft → Open → Closed; a closed session can be reopened (audited). The date cannot change once tasks exist. One session per date + venue |
| Callback | Optional "call back at" date-time on an attempt; shown in lists and filterable. No reminder service |
| Contact deletion | No delete in the app or Django Admin; history uses PROTECT foreign keys |
| Merging | Not implemented. Duplicates (same phone) are flagged on create/edit/import and need explicit confirmation |

### Access and privacy
| Area | Decision |
|---|---|
| Callers | See only their own **non-withdrawn** tasks (other callers' tasks → 404). No access to contact list, contact records, sessions, reports, exports, import or audit (403) |
| Caller contact view | Name, area, phone (tap-to-call), attempts on that task, and their own earlier outcomes for that contact. Coordinator notes are not shown |
| Do not call | Phone hidden from callers; no new attempts; excluded from contact and task exports unless "include Do not call" is chosen (audited) |
| Exports | Coordinators only; every export audited; task exports contain no phone numbers; formula-injection protection on CSV and XLSX |
| Audit log | Status changes, allocation operations (with every move), cycle creation, task moves/withdrawals, call attempts, session changes, import upload/mapping/resolution/commit/cancel, exports. Phone numbers are never written to the audit log. Coordinators can read it; nobody can edit it |
| Uploads | .xlsx/.csv only, 5 MB, 5 000 rows; parsed with `defusedxml` protection; the file itself is not stored — every row's raw values are kept in the staged batch |

### Rotation
| Area | Decision |
|---|---|
| Operations | Assign/move selected contacts; move a whole list; swap two lists; rotate lists among N callers (alphabetical order, each list to the next caller). All previewed, then applied atomically with effective date, reason and optional cycle |
| Stale preview | The preview carries a fingerprint; if allocations changed since, apply is refused and a fresh preview is required |
| Cycle length | `ALLOCATION_CYCLE_MONTHS` (default 3) suggests the next cycle's dates; "rotation due" appears `ROTATION_REMINDER_DAYS` (default 14) before the planned end |

### Import
| Area | Decision |
|---|---|
| Exact matches | A row whose normalised phone + name match an existing contact is "Already imported" and linked; other problems on that row become warnings (nothing from it is written) |
| Existing contacts | Never re-allocated by an import; differences are listed in the summary for manual reassignment |
| Commit gates | No unresolved rows; mapping confirmed; caller-column confirmation ticked; cycle chosen/created with start date confirmed (cannot be in the future); discrepancies acknowledged |
| Unallocated rows | A blank or unknown caller must be mapped to a user or explicitly marked "no caller" |

### Not done / outstanding
- The real import itself (questions B-1 and B-2 are resolved).
- Deployment, backups and UAT (N-4); Docker and CI have not been executed.
- Actual attendance, reminders and historical outcome import remain out of scope.
