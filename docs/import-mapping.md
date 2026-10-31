# Initial Workbook Import — Proposed Mapping (v1)

Source: `2026 EMS DATA.xlsx`, structure as described by the business on 2026-10-29.
The real workbook has **not** been opened by the development team; development and tests use
a synthetic workbook with the same sheet and column layout. The real file must never be
committed to source control (`*.xlsx` and `*.csv` are git-ignored).

Labels follow `docs/requirements.md`: [C] confirmed, [D] accepted default, [A] assumption, [P] proposal.

---

## 1. Sheets and how each is used

| Sheet | Use in MVP import | Label |
|---|---|---|
| `EMS STALL SEWA` | **Primary source** — one row per contact; creates Contacts and initial Allocations | [C] |
| `2026 Calling Sewa status` | **Optional cross-check only** (off by default; not reliably maintained) — expected `Total Assigned` per caller. No records created | [C] |
| `Weekly Data` | Not imported. Weekly aggregates; candidate for a later "legacy weekly summary" if approved | [C] |
| `Calling Sewa status` (older) | Not imported | [C] |

Historical weekly columns in any sheet are **not** migrated into call attempts or attendance [C].
They remain in the stored raw row of the import batch so nothing is lost [C].

## 2. Column mapping — `EMS STALL SEWA`

Header matching ignores case, surrounding spaces and repeated spaces (the header is spelled
`CALLING CO-ORDINATER` in the workbook). The coordinator confirms the mapping on the mapping
screen before validation runs; the confirmed mapping is stored on the batch.

| Workbook column | Target | Required | Transformation | Label |
|---|---|---|---|---|
| `DATE` | `Contact.registration_date` | Yes | Excel date cell → date; text parsed DD/MM/YYYY (also DD-MM-YYYY, DD.MM.YYYY); ambiguous or future dates flagged | [C] mapping / [A] DD/MM |
| `NAME` | `Contact.full_name` | Yes | Trim, collapse spaces; **case preserved** | [C] |
| `MOBILE NO` | `Contact.phone_primary` (+ `phone_secondary`) | Yes | Strip spaces/dashes/brackets; numeric cells read as integers (no float/scientific-notation loss); default region +91; validated with `phonenumbers`; a cell containing two numbers (`/`, `,`, newline) → first = primary, second = secondary, flagged for review; original text kept | [C] / [A] +91 |
| `AREA` | `Contact.area` | Yes | Trim only; **no case change, spelling correction or merging** | [D] |
| `QUALIFICATION` | `Contact.qualification` (optional) | No | Trim only | [A] |
| `SEWA CONDUCTED BY` | `Contact.collected_by_name` (optional, free text) | No | Trim only; **not** matched to user accounts | [A] — role confirmed on mapping screen |
| `CALLING CO-ORDINATER` | **Allocated caller** → `Allocation.caller` | Yes, for allocation | Name resolution, §3 | [C] confirmed 2026-10-31: the Saint who makes the calls |
| Historical weekly columns | Not mapped | — | Kept in `ImportRow.raw_values` only | [C] |
| Any other unmapped column | Not mapped | — | Kept in `ImportRow.raw_values` only (not copied to the contact, so weekly history is never migrated by accident) | [P] as built |

Every committed contact stores `legacy_data.import = {batch, sheet, row}` and
`legacy_data.original = {header: value}` for the mapped name, phone, area, date and caller
columns exactly as they appeared in the workbook (original phone text is preserved alongside
the normalised number).

## 3. Identifying and preserving the existing caller allocation

1. **Distinct names.** The import lists every distinct value in the caller column with its
   row count.
2. **Role check (requirement 14).** The preview cross-references those names against:
   - `2026 Calling Sewa status` → `Name` values (expected callers),
   - `2026 Calling Sewa status` → `Co-ordinator` values (expected coordinators),
   - distinct `SEWA CONDUCTED BY` values.
   If the caller-column names mostly match `Co-ordinator` rather than `Name`, or overlap heavily
   with `SEWA CONDUCTED BY`, the import shows a **blocking warning** that the column may not
   hold callers, and commit is disabled until a coordinator confirms the column's meaning.
3. **Name → user resolution**, in order:
   1. saved `CallerAlias` (normalised: lower-case, trimmed, single spaces, punctuation removed);
   2. exact match on user's full name or username (normalised);
   3. otherwise **Needs resolution**: coordinator picks a user (optionally saving the alias),
      or marks the rows "import without allocation" with a reason.
   A name matching two users is always **Needs resolution**. Matched users without the Caller
   role produce a warning.
4. **Effective date.** Before commit the coordinator selects or creates the current
   `AllocationCycle` and confirms its start date; every imported allocation gets
   `effective_from = cycle start date`, `change_type = INITIAL_IMPORT` [D]. The registration
   date is never used [D].
5. **Reconciliation.** The summary compares, per caller, the number of imported allocations with
   `Total Assigned` from `2026 Calling Sewa status`. Mismatches are highlighted and must be
   acknowledged before commit (they are not silently corrected).

## 4. Validation outcomes per row

| Status | Causes | Commit behaviour |
|---|---|---|
| ✅ Ready | All checks pass | Imported |
| ⚠️ Warning | Two numbers in phone cell, future/odd date, caller lacks Caller role, phone already used by a differently named contact (possible family phone) | Imported after batch-level acknowledgement |
| 🟠 Needs resolution | Missing required field, unparseable date, invalid phone, possible duplicate (same normalised phone + similar name, in file or in database), unmatched/ambiguous caller | Coordinator must fix value, choose *merge with existing* / *create new*, map caller, or *skip with reason* |
| ↺ Already imported | Same normalised phone + normalised name as a contact created by an earlier batch | Linked, not duplicated |
| ⏭ Skipped | Coordinator decision (reason mandatory) | Not imported; raw row and reason kept in the batch and the summary |

Commit is only enabled when no row is in *Needs resolution*.

## 5. Repeat safety

- SHA-256 of the uploaded file is stored; re-uploading the same file shows the earlier batch.
- Natural key per contact = normalised phone + normalised name; a re-import of the same rows
  creates **zero** new contacts or allocations.
- A re-import never changes an existing contact's allocation; differences are reported for a
  coordinator to apply as a normal reassignment.

## 6. Commit and summary

- One database transaction per batch: Contacts, initial Allocations, one `AllocationOperation`,
  audit entries. Any failure rolls back everything.
- **Import summary** (on screen and downloadable CSV): rows read; created; linked to existing;
  skipped (with reasons); warnings acknowledged; allocations per caller vs `Total Assigned`;
  contacts imported without allocation.
- The uploaded file and staged rows are retained in restricted storage until the retention
  decision (N-2).

## 6b. Changes (2026-10-31)

- **Status sheet is optional** and off by default ("Also compare caller counts with the
  '2026 Calling Sewa status' sheet" on the upload form). Without it nothing is compared and no
  Total Assigned discrepancies are raised. It is still never used to change data.
- **Caller accounts from the workbook.** On the review page, caller names that match no account
  are listed with a suggested username (e.g. "Shalini ji" → `shalini.ji`). Names that look like an
  existing account are unticked by default to avoid duplicate people. Ticked names get
  Caller-only accounts with generated 10-character passwords (no look-alike characters) in one
  all-or-nothing step; a caller alias is saved so their rows match automatically. The username
  and password list is shown once (copy / print / download), never stored readable, and
  passwords are not written to the audit log. Coordinators and admins can use it.

## 6a. As implemented (2026-10-30)

- Screens: Import → Upload → Map columns → Preview (counts, discrepancies, caller-name table,
  status-sheet comparison, rows by status, per-row "Resolve") → Commit → Summary + row report CSV.
- Exact matches (same normalised phone + name) are "Already imported"; other problems on such
  rows become warnings because nothing from them is written.
- The uploaded file is not stored; all source values of every row are kept in the batch.
- The commit runs in one transaction (including creating the cycle); any failure leaves the
  batch staged and nothing imported.
- Outstanding: a dry run of the real workbook (upload + preview only, no commit) and coordinator
  review before committing (B-1 and B-2 are resolved).

## 7. Synthetic test workbook

`manage.py generate_synthetic_workbook <file.xlsx>` (module `apps/imports/synthetic.py`)
produces `EMS STALL SEWA` and `2026 Calling Sewa status` sheets with ~120 fake
contacts and fake callers, including: duplicate phones, invalid and two-number phone cells,
numeric phone cells, text and Excel-serial dates, blank areas, caller-name spelling variants,
an unknown caller, and historical weekly columns. Expected import results are asserted in tests.
