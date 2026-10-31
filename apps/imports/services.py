"""Workbook import: stage → validate → resolve → commit (docs/import-mapping.md).

Nothing touches contacts or allocations until ``commit_batch``, which runs in one
transaction. Raw source values are kept on every ``ImportRow``.
"""

import re
from collections import Counter, defaultdict

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts import team
from apps.accounts.models import User
from apps.allocations.models import ChangeType
from apps.allocations.services import PlannedChange, apply_plan, current_allocation
from apps.audit.services import log_event
from apps.contacts.models import Contact, StatusReason
from apps.contacts.services import create_contact
from apps.core.phones import parse_phone_cell, raw_phone_text
from apps.core.text import clean_text, names_similar, normalize_name

from . import parsing
from .models import BatchStatus, CallerAlias, ImportBatch, ImportRow, RowAction, RowOutcome, RowStatus

UNALLOCATED = "unallocated"
KEY_ERRORS = {"missing_name", "missing_phone", "invalid_phone", "link_missing"}
MAX_LENGTHS = {"full_name": 150, "area": 150, "qualification": 150, "collected_by": 150}


class ImportProblem(Exception):
    """Raised when a batch cannot be staged or committed."""


# --- Staging -----------------------------------------------------------------


@transaction.atomic
def stage_upload(uploaded_file, actor, *, contact_sheet="", status_sheet="", use_status_sheet=False):
    """Read the workbook into a staged batch. The status sheet is only read when asked for,
    because it is not always kept up to date; it is then used purely as a cross-check."""
    sha = parsing.sha256_of(uploaded_file)
    file_type, sheets = parsing.read_sheets(uploaded_file)

    contact_name = contact_sheet.strip() or parsing.find_sheet(sheets, parsing.CONTACT_SHEET)
    if not contact_name:
        contact_name = next(iter(sheets)) if len(sheets) == 1 else None
    if contact_name not in sheets:
        raise ImportProblem(
            "Could not find the contact sheet. Available sheets: " + ", ".join(sheets) + ". "
            "Enter the sheet name in the upload form."
        )
    status_name = ""
    if use_status_sheet:
        status_name = status_sheet.strip() or parsing.find_sheet(sheets, parsing.STATUS_SHEET) or ""
        if not status_name:
            raise ImportProblem(
                "No '2026 Calling Sewa status' sheet was found. Untick the comparison option, "
                "or enter the status sheet's name. Available sheets: " + ", ".join(sheets) + "."
            )
        if status_name not in sheets:
            raise ImportProblem(f"Sheet '{status_name}' was not found.")

    known = [alias for _, _, _, aliases in parsing.TARGET_FIELDS for alias in aliases]
    rows = sheets[contact_name]
    header_index = parsing.detect_header_row(rows, known)
    headers, records = parsing.table_from_rows(rows, header_index)
    if not records:
        raise ImportProblem(f"Sheet '{contact_name}' has no data rows.")
    if len(records) > settings.IMPORT_MAX_ROWS:
        raise ImportProblem("Too many rows in the contact sheet.")

    caller_records, _ = parsing.parse_status_sheet(sheets[status_name]) if status_name else ([], [])
    batch = ImportBatch.objects.create(
        uploaded_by=actor,
        original_filename=uploaded_file.name[:255],
        file_sha256=sha,
        file_type=file_type,
        sheet_names=list(sheets),
        contact_sheet=contact_name,
        status_sheet=status_name,
        header_row=header_index + 1,
        headers=headers,
        column_mapping=parsing.guess_mapping(headers),
        caller_records=caller_records,
    )
    ImportRow.objects.bulk_create(
        ImportRow(batch=batch, row_number=row_number, raw_values=values) for row_number, values in records
    )
    log_event(
        actor,
        "import.upload",
        f"Staged {uploaded_file.name}: {len(records)} rows",
        batch,
        sha256=sha,
        sheet=contact_name,
        status_sheet=status_name,
    )
    return batch


def previous_commits(batch):
    return ImportBatch.objects.filter(file_sha256=batch.file_sha256, status=BatchStatus.COMMITTED).exclude(
        pk=batch.pk
    )


# --- Caller resolution ---------------------------------------------------------


class CallerResolver:
    """Workbook name → user, via batch mapping, saved alias, or exact name/username."""

    def __init__(self, batch):
        self.mapping = batch.caller_mapping or {}
        self.aliases = {a.alias: a.user for a in CallerAlias.objects.select_related("user")}
        self.by_name = defaultdict(set)
        for user in User.objects.filter(is_active=True):
            for key in {normalize_name(user.get_full_name()), normalize_name(user.username)}:
                if key:
                    self.by_name[key].add(user)
        self.users = {u.pk: u for u in User.objects.filter(is_active=True)}

    def resolve(self, name):
        """Return (user | None, state) where state is mapped/alias/matched/unallocated/ambiguous/unmatched/blank."""
        key = normalize_name(name)
        chosen = self.mapping.get(key)
        if chosen == UNALLOCATED:
            return None, "unallocated"
        if chosen and int(chosen) in self.users:
            return self.users[int(chosen)], "mapped"
        if not key:
            return None, "blank"
        if key in self.aliases and self.aliases[key].is_active:
            return self.aliases[key], "alias"
        matches = self.by_name.get(key, set())
        if len(matches) == 1:
            return next(iter(matches)), "matched"
        return None, "ambiguous" if matches else "unmatched"


# --- Validation ----------------------------------------------------------------


def _issue(level, code, message):
    return {"level": level, "code": code, "message": message}


def source_value(batch, row, field):
    if field in row.overrides:
        return row.overrides[field]
    header = batch.column_mapping.get(field)
    return row.raw_values.get(header) if header else None


def compute_values(batch, row, resolver):
    """Normalised values and field-level issues for one row."""
    issues = []
    values = {}

    name = clean_text(source_value(batch, row, "full_name"))
    values["full_name"] = name
    if not name:
        issues.append(_issue("error", "missing_name", "Name is missing."))

    raw_phone = source_value(batch, row, "phone")
    phones = parse_phone_cell(raw_phone)
    values["phone_raw"] = raw_phone_text(raw_phone)
    values["phone"] = phones[0].e164 if phones else None
    values["phone_secondary"] = None
    if not phones:
        issues.append(_issue("error", "missing_phone", "Mobile number is missing."))
    elif not phones[0].is_valid:
        issues.append(_issue("error", "invalid_phone", f"Mobile number '{phones[0].raw}' is not valid."))
    if len(phones) > 1:
        issues.append(
            _issue("warning", "two_phones", "Cell has more than one number; the second is kept as secondary.")
        )
        if phones[1].is_valid:
            values["phone_secondary"] = phones[1].e164
        else:
            issues.append(
                _issue(
                    "warning",
                    "invalid_secondary",
                    f"Second number '{phones[1].raw}' is not valid and was not kept.",
                )
            )
        if len(phones) > 2:
            issues.append(
                _issue(
                    "warning",
                    "extra_phones",
                    "More than two numbers; extras are kept in the original values only.",
                )
            )

    area_value = source_value(batch, row, "area")
    area = "" if area_value is None else str(area_value).strip()  # trim only (decision 15)
    values["area"] = area
    if not area:
        issues.append(_issue("error", "missing_area", "Area is missing."))

    reg_date, ambiguous = parsing.parse_date_cell(source_value(batch, row, "registration_date"))
    values["registration_date"] = reg_date.isoformat() if reg_date else None
    if source_value(batch, row, "registration_date") in (None, ""):
        issues.append(_issue("error", "missing_date", "Date is missing."))
    elif reg_date is None:
        issues.append(_issue("error", "invalid_date", "Date could not be read (use DD/MM/YYYY)."))
    else:
        if reg_date > timezone.localdate():
            issues.append(_issue("warning", "future_date", "Date is in the future."))
        if ambiguous:
            issues.append(
                _issue("warning", "ambiguous_date", f"Date read as {reg_date:%d %b %Y} (day first).")
            )

    values["qualification"] = clean_text(source_value(batch, row, "qualification"))
    values["collected_by"] = clean_text(source_value(batch, row, "collected_by"))
    for field, limit in MAX_LENGTHS.items():
        if len(values.get(field) or "") > limit:
            issues.append(
                _issue(
                    "error",
                    f"{field}_too_long",
                    f"{field.replace('_', ' ').title()} is longer than {limit} characters.",
                )
            )

    caller_name = clean_text(source_value(batch, row, "caller")) if batch.column_mapping.get("caller") else ""
    values["caller_name"] = caller_name
    user, state = resolver.resolve(caller_name)
    values["caller_id"] = user.pk if user else None
    values["caller_state"] = state
    if state in {"blank", "unmatched", "ambiguous"}:
        label = {
            "blank": "No caller given",
            "unmatched": f"Caller '{caller_name}' does not match a user",
            "ambiguous": f"Caller '{caller_name}' matches more than one user",
        }[state]
        issues.append(_issue("error", f"caller_{state}", label + " — map it in the caller table."))
    elif user and not user.is_caller:
        issues.append(_issue("warning", "caller_role", f"{user} does not have the Caller role."))
    return values, issues


def validate_batch(batch):
    """Recompute values, issues and status for every row. Returns status counts."""
    resolver = CallerResolver(batch)
    rows = list(batch.rows.all())
    for row in rows:
        row.values, row.issues = compute_values(batch, row, resolver)
        row.candidate_ids = []

    phones = {r.values["phone"] for r in rows if r.values.get("phone")} | {
        r.values["phone_secondary"] for r in rows if r.values.get("phone_secondary")
    }
    existing = defaultdict(list)
    for contact in Contact.objects.filter(Q(phone_primary__in=phones) | Q(phone_secondary__in=phones)):
        for phone in {contact.phone_primary, contact.phone_secondary} - {""}:
            existing[phone].append(contact)

    first_seen = defaultdict(list)
    already = {}
    for row in rows:
        if row.action == RowAction.SKIP:
            continue
        phone, name = row.values.get("phone"), row.values.get("full_name")
        if not phone:
            continue
        # Against earlier rows in this file.
        for earlier in first_seen[phone]:
            if names_similar(earlier.values["full_name"], name):
                if row.action not in {RowAction.CREATE, RowAction.LINK}:
                    row.issues.append(
                        _issue(
                            "error",
                            "duplicate_in_file",
                            f"Same phone and similar name as row {earlier.row_number}.",
                        )
                    )
                break
        else:
            if first_seen[phone]:
                row.issues.append(
                    _issue(
                        "warning",
                        "shared_phone_in_file",
                        f"Phone also used by row {first_seen[phone][0].row_number} (different name).",
                    )
                )
        first_seen[phone].append(row)
        # Against contacts already in the database.
        candidates = {
            c.pk: c for p in {phone, row.values.get("phone_secondary")} if p for c in existing.get(p, [])
        }
        row.candidate_ids = sorted(candidates)
        exact = [c for c in candidates.values() if normalize_name(c.full_name) == normalize_name(name)]
        similar = [c for c in candidates.values() if c not in exact and names_similar(c.full_name, name)]
        if exact and row.action != RowAction.LINK:
            already[row.pk] = exact[0]
        elif similar and row.action not in {RowAction.CREATE, RowAction.LINK}:
            row.issues.append(
                _issue(
                    "error",
                    "duplicate_in_database",
                    f"Possible duplicate of existing contact {similar[0]} — link or create new.",
                )
            )
        elif candidates and not exact and not similar:
            row.issues.append(
                _issue(
                    "warning",
                    "shared_phone_in_database",
                    "Phone already used by a differently named contact (shared phone?).",
                )
            )

    for row in rows:
        if row.action == RowAction.LINK and row.link_contact_id is None:
            row.issues.append(_issue("error", "link_missing", "Choose the contact to link to."))
        if row.pk in already and row.action != RowAction.SKIP:
            # Exact match (phone + name): nothing from this row is written, so other
            # problems no longer block it. Name and phone were valid to match at all.
            row.issues = [
                {**i, "level": "warning", "message": i["message"] + " (ignored: contact already exists)"}
                if i["level"] == "error" and i["code"] not in KEY_ERRORS
                else i
                for i in row.issues
            ]
        if row.action == RowAction.SKIP:
            row.status = RowStatus.SKIPPED
        elif row.issues_at("error"):
            row.status = RowStatus.NEEDS_RESOLUTION
        elif row.pk in already:
            row.status = RowStatus.ALREADY_IMPORTED
            row.link_contact = already[row.pk]
        elif row.issues_at("warning"):
            row.status = RowStatus.WARNING
        else:
            row.status = RowStatus.READY
        if row.action != RowAction.LINK and row.status != RowStatus.ALREADY_IMPORTED:
            row.link_contact = None
    ImportRow.objects.bulk_update(rows, ["values", "issues", "status", "candidate_ids", "link_contact"])

    batch.discrepancies = reconcile(batch, rows, resolver)
    batch.summary = {**batch.summary, "counts": dict(Counter(r.status for r in rows))}
    batch.discrepancies_acknowledged = False
    batch.save(update_fields=["discrepancies", "summary", "discrepancies_acknowledged"])
    return batch.summary["counts"]


# --- Reconciliation ------------------------------------------------------------


def caller_name_counts(rows):
    """Distinct values of the caller column with row counts (excluding skipped rows)."""
    counts = Counter(r.values.get("caller_name", "") for r in rows if r.status != RowStatus.SKIPPED)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))


def per_caller_counts(rows):
    counts = Counter(r.values.get("caller_id") for r in rows if r.status != RowStatus.SKIPPED)
    return counts


def reconcile(batch, rows, resolver):
    """Batch-level discrepancies that must be acknowledged before commit."""
    issues = []
    if previous_commits(batch).exists():
        ids = ", ".join(f"#{b.pk}" for b in previous_commits(batch))
        issues.append(
            {
                "code": "same_file",
                "message": f"This exact file was already imported (batch {ids}). "
                "Existing contacts will be linked, not duplicated.",
            }
        )

    caller_values = {normalize_name(name) for name, _ in caller_name_counts(rows) if name}
    status_names = {normalize_name(r["name"]) for r in batch.caller_records}
    status_coordinators = {normalize_name(r["coordinator"]) for r in batch.caller_records if r["coordinator"]}
    collectors = {normalize_name(r.values.get("collected_by")) for r in rows if r.values.get("collected_by")}
    if caller_values:
        as_callers = len(caller_values & status_names)
        as_coordinators = len(caller_values & status_coordinators)
        as_collectors = len(caller_values & collectors)
        if batch.caller_records and as_coordinators > as_callers:
            issues.append(
                {
                    "code": "caller_column_role",
                    "message": (
                        f"The '{batch.column_mapping.get('caller')}' values match the status sheet's Co-ordinator column "
                        f"({as_coordinators}) more than its caller names ({as_callers}). This column may hold coordinators, "
                        "not callers. Confirm its meaning before importing."
                    ),
                }
            )
        if as_collectors and as_collectors * 2 >= len(caller_values):
            issues.append(
                {
                    "code": "caller_vs_collector",
                    "message": (
                        f"{as_collectors} of {len(caller_values)} caller names also appear in 'Sewa conducted by'. "
                        "Check that the caller column is not the stall seva column."
                    ),
                }
            )

    # The status sheet comparison is optional (it is not always maintained); without it there is
    # nothing to compare, and that is not a discrepancy.
    derived = per_caller_counts(rows)
    seen_users = set()
    for record in batch.caller_records:
        user, state = resolver.resolve(record["name"])
        if user is None:
            if record["total_assigned"]:
                issues.append(
                    {
                        "code": "status_caller_unmatched",
                        "message": (
                            f"Status sheet caller '{record['name']}' (Total Assigned {record['total_assigned_raw']}) "
                            "does not match a user or any mapped caller."
                        ),
                    }
                )
            continue
        seen_users.add(user.pk)
        count = derived.get(user.pk, 0)
        if record["total_assigned"] is None:
            issues.append(
                {
                    "code": "total_not_number",
                    "message": (
                        f"{user}: Total Assigned '{record['total_assigned_raw']}' is not a number; workbook rows give {count}."
                    ),
                }
            )
        elif record["total_assigned"] != count:
            issues.append(
                {
                    "code": "count_mismatch",
                    "message": (
                        f"{user}: workbook rows give {count} contact(s) but Total Assigned says {record['total_assigned']}."
                    ),
                }
            )
    if batch.caller_records:
        for user_id, count in derived.items():
            if user_id and user_id not in seen_users:
                user = resolver.users.get(user_id)
                issues.append(
                    {
                        "code": "caller_not_in_status",
                        "message": (
                            f"{user} has {count} contact(s) in the workbook but no row in the status sheet."
                        ),
                    }
                )
    unallocated = sum(
        1 for r in rows if r.status != RowStatus.SKIPPED and r.values.get("caller_state") == "unallocated"
    )
    if unallocated:
        issues.append(
            {"code": "unallocated", "message": f"{unallocated} contact(s) will be imported without a caller."}
        )
    return issues


def status_record_rows(batch):
    """Status-sheet records with the resolved user and derived count, for display."""
    resolver = CallerResolver(batch)
    derived = per_caller_counts(list(batch.rows.all()))
    result = []
    for record in batch.caller_records:
        user, state = resolver.resolve(record["name"])
        result.append(
            {**record, "user": user, "state": state, "derived": derived.get(user.pk, 0) if user else None}
        )
    return result


# --- Resolution helpers ----------------------------------------------------------


@transaction.atomic
def set_caller_mapping(batch, name, choice, actor, save_alias=False):
    """``choice`` is a user id, ``UNALLOCATED`` or '' (clear)."""
    key = normalize_name(name)
    mapping = dict(batch.caller_mapping or {})
    if choice:
        mapping[key] = choice
    else:
        mapping.pop(key, None)
    batch.caller_mapping = mapping
    batch.save(update_fields=["caller_mapping"])
    if save_alias and choice and choice != UNALLOCATED and key:
        CallerAlias.objects.update_or_create(
            alias=key, defaults={"user_id": int(choice), "created_by": actor}
        )
    log_event(actor, "import.caller_mapping", f"Batch #{batch.pk}: '{name}' → {choice or 'cleared'}", batch)
    validate_batch(batch)


# --- Review summary (what the coordinator sees before confirming) ----------------------

ISSUE_GROUPS = {
    "duplicates": {"duplicate_in_file", "duplicate_in_database"},
    "invalid_phones": {"invalid_phone", "missing_phone"},
    "missing_fields": {"missing_name", "missing_area", "missing_date", "invalid_date"},
    "unmatched_callers": {"caller_unmatched", "caller_ambiguous", "caller_blank"},
}


def review_summary(batch):
    """Counts for the review step and a preview of what committing would do."""
    rows = list(batch.rows.all())
    counts = Counter(r.status for r in rows)
    issues = {group: 0 for group in ISSUE_GROUPS}
    for row in rows:
        if row.status == RowStatus.SKIPPED:
            continue
        codes = {i["code"] for i in row.issues if i["level"] == "error"}
        for group, members in ISSUE_GROUPS.items():
            if codes & members:
                issues[group] += 1
    importable = [r for r in rows if r.status in {RowStatus.READY, RowStatus.WARNING}]
    to_create = [r for r in importable if r.action != RowAction.LINK]
    users = {
        u.pk: u for u in User.objects.filter(pk__in={r.values.get("caller_id") for r in to_create} - {None})
    }
    per_caller = Counter(
        str(users[r.values["caller_id"]]) for r in to_create if r.values.get("caller_id") in users
    )
    return {
        "total": len(rows),
        "ready": counts.get(RowStatus.READY, 0),
        "warning": counts.get(RowStatus.WARNING, 0),
        "needs": counts.get(RowStatus.NEEDS_RESOLUTION, 0),
        "already": counts.get(RowStatus.ALREADY_IMPORTED, 0),
        "skipped": counts.get(RowStatus.SKIPPED, 0),
        "issues": issues,
        "to_create": len(to_create),
        "to_link": counts.get(RowStatus.ALREADY_IMPORTED, 0) + (len(importable) - len(to_create)),
        "to_allocate": sum(per_caller.values()),
        "unallocated": len(to_create) - sum(per_caller.values()),
        "per_caller": sorted(per_caller.items(), key=lambda kv: kv[0].lower()),
    }


# --- Caller accounts from the workbook ------------------------------------------------


def unmatched_callers(batch):
    """Workbook caller names with no account yet: [{name, rows, username, similar}].

    ``similar`` lists existing accounts with a similar name (possible spelling variant),
    so the coordinator can map instead of creating a duplicate person.
    """
    if not batch.column_mapping.get("caller"):
        return []
    resolver = CallerResolver(batch)
    taken = team.taken_usernames()
    users = list(User.objects.filter(is_active=True))
    by_key = {}
    # Most frequent spelling first, so "Shalini ji" wins over a stray "shalini  JI".
    for name, count in caller_name_counts(list(batch.rows.all())):
        key = normalize_name(name)
        if not key or resolver.resolve(name)[1] != "unmatched":
            continue
        if key in by_key:
            by_key[key]["rows"] += count
            continue
        similar = [u for u in users if names_similar(u.get_full_name() or u.username, name)]
        by_key[key] = {
            "name": name,
            "rows": count,
            "username": team.suggest_username(name, taken),
            "similar": similar,
        }
    return list(by_key.values())


@transaction.atomic
def create_callers_from_workbook(batch, entries, actor):
    """Create Caller-only accounts for workbook names and link them to the batch.

    ``entries`` is [(workbook name, username)]. Returns [(name, username, password)]; the
    passwords exist only in this return value (they are stored hashed), so the caller of
    this function must show them once. All accounts are created, or none.
    """
    if batch.status != BatchStatus.STAGED:
        raise ImportProblem("This batch is no longer staged.")
    unmatched = {normalize_name(item["name"]) for item in unmatched_callers(batch)}
    created, seen = [], set()
    for name, username in entries:
        key = normalize_name(name)
        username = clean_text(username)
        if key not in unmatched:
            raise ImportProblem(f"'{name}' already matches an account or is not in this workbook.")
        if key in seen:
            continue
        seen.add(key)
        if not username or not re.fullmatch(r"[\w.@+-]+", username):
            raise ImportProblem(f"Username for '{name}' may contain only letters, digits and @ . + - _")
        if User.objects.filter(username__iexact=username).exists():
            raise ImportProblem(f"The username '{username}' is already taken.")
        first_name, last_name = team.split_name(clean_text(name))
        password = team.generate_password()
        user = team.create_caller(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email="",
            password=password,
            actor=actor,
        )
        CallerAlias.objects.update_or_create(alias=key, defaults={"user": user, "created_by": actor})
        created.append((clean_text(name), username, password))
    if not created:
        raise ImportProblem("Tick at least one name to create an account for.")
    log_event(
        actor,
        "import.create_callers",
        f"Batch #{batch.pk}: created {len(created)} caller account(s)",
        batch,
        usernames=[username for _, username, _ in created],  # never the passwords
    )
    validate_batch(batch)
    return created


@transaction.atomic
def update_row(row, *, overrides, action, link_contact, skip_reason, actor):
    row.overrides = {k: v for k, v in overrides.items() if v not in (None, "")}
    row.action = action
    row.link_contact = link_contact if action == RowAction.LINK else None
    row.skip_reason = skip_reason if action == RowAction.SKIP else ""
    row.save(update_fields=["overrides", "action", "link_contact", "skip_reason"])
    log_event(
        actor,
        "import.row_update",
        f"Batch #{row.batch_id} row {row.row_number}: {action or 'auto'}",
        row.batch,
        row=row.row_number,
        fields=sorted(row.overrides),
    )
    validate_batch(row.batch)


# --- Commit ------------------------------------------------------------------------


def commit_blockers(batch):
    blockers = []
    if batch.status != BatchStatus.STAGED:
        blockers.append("This batch is not staged.")
    if not batch.mapping_confirmed:
        blockers.append("Confirm the column mapping.")
    if batch.rows.filter(status=RowStatus.NEEDS_RESOLUTION).exists():
        blockers.append("Some rows still need resolution.")
    if not batch.caller_column_confirmed:
        blockers.append("Confirm that the caller column holds each contact's allocated caller.")
    if batch.cycle is None:
        blockers.append("Choose the current allocation cycle and confirm its start date.")
    if batch.discrepancies and not batch.discrepancies_acknowledged:
        blockers.append("Acknowledge the discrepancies listed above.")
    return blockers


@transaction.atomic
def commit_batch(batch, actor):
    batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
    acknowledged = batch.discrepancies_acknowledged
    before = list(batch.discrepancies)
    validate_batch(batch)
    batch.refresh_from_db()
    if batch.discrepancies == before:
        batch.discrepancies_acknowledged = acknowledged  # unchanged since acknowledgement
    blockers = commit_blockers(batch)
    if blockers:
        raise ImportProblem(" ".join(blockers))

    cycle = batch.cycle
    users = {u.pk: u for u in User.objects.all()}
    rows = list(batch.rows.select_related("link_contact").order_by("row_number"))
    created, linked, skipped, allocation_notes = [], [], [], []
    changes = []
    for row in rows:
        if row.status == RowStatus.SKIPPED:
            row.outcome = RowOutcome.SKIPPED
            skipped.append(row)
            continue
        caller = users.get(row.values.get("caller_id"))
        if row.status == RowStatus.ALREADY_IMPORTED or row.action == RowAction.LINK:
            contact = row.link_contact
            row.contact, row.outcome = contact, RowOutcome.LINKED
            linked.append(row)
            current = current_allocation(contact)
            if caller and (current is None or current.caller_id != caller.pk):
                allocation_notes.append(
                    f"Row {row.row_number}: {contact} is allocated to {current.caller if current else 'nobody'}; "
                    f"workbook says {caller}. Not changed — reassign manually if needed."
                )
            continue
        contact = create_contact(
            {
                "full_name": row.values["full_name"],
                "phone_primary": row.values["phone"],
                "phone_secondary": row.values.get("phone_secondary") or "",
                "area": row.values["area"],
                "registration_date": row.values["registration_date"],
                "qualification": row.values.get("qualification", ""),
                "collected_by_name": row.values.get("collected_by", ""),
                "notes": "",
            },
            actor,
            reason=StatusReason.IMPORTED,
            reason_text=f"Import batch #{batch.pk}, row {row.row_number}",
            legacy_data={
                "import": {"batch": batch.pk, "sheet": batch.contact_sheet, "row": row.row_number},
                "original": {
                    batch.column_mapping[f]: row.raw_values.get(batch.column_mapping[f])
                    for f in ("full_name", "phone", "area", "registration_date", "caller")
                    if batch.column_mapping.get(f)
                },
            },
        )
        row.contact, row.outcome = contact, RowOutcome.CREATED
        created.append(row)
        if caller:
            changes.append(PlannedChange(contact, None, caller))

    operation = None
    if changes:
        operation = apply_plan(
            changes,
            kind=ChangeType.INITIAL_IMPORT,
            effective_date=cycle.start_date,
            actor=actor,
            reason=f"Initial import batch #{batch.pk} ({batch.original_filename})",
            cycle=cycle,
        )
    ImportRow.objects.bulk_update(rows, ["contact", "outcome"])

    per_caller = Counter(str(ch.to_caller) for ch in changes)
    batch.status = BatchStatus.COMMITTED
    batch.committed_at = timezone.now()
    batch.committed_by = actor
    batch.last_error = ""
    batch.summary = {
        **batch.summary,
        "result": {
            "rows": len(rows),
            "created": len(created),
            "linked": len(linked),
            "skipped": len(skipped),
            "allocated": len(changes),
            "unallocated": len(created) - len(changes),
            "per_caller": dict(sorted(per_caller.items())),
            "allocation_notes": allocation_notes,
            "operation": operation.pk if operation else None,
            "cycle": cycle.pk,
            "effective_date": cycle.start_date.isoformat(),
            "acknowledged_discrepancies": batch.discrepancies,
        },
    }
    batch.save()
    log_event(
        actor,
        "import.commit",
        f"Imported batch #{batch.pk}: {len(created)} created, {len(linked)} linked, {len(skipped)} skipped",
        batch,
        **batch.summary["result"],
    )
    return batch


def cancel_batch(batch, actor):
    if batch.status != BatchStatus.STAGED:
        raise ImportProblem("Only a staged batch can be cancelled.")
    batch.status = BatchStatus.CANCELLED
    batch.save(update_fields=["status"])
    log_event(actor, "import.cancel", f"Cancelled batch #{batch.pk}", batch)
