from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.views import View
from django.views.generic import ListView

from apps.allocations.services import AllocationError, callers_queryset, create_cycle
from apps.audit.services import log_event
from apps.contacts.models import Contact
from apps.core.exports import csv_response
from apps.core.permissions import CoordinatorRequiredMixin

from . import parsing, services
from .forms import CallerMappingForm, CommitForm, MappingForm, RowForm, UploadForm
from .models import ImportBatch, ImportRow, RowStatus


class BatchListView(CoordinatorRequiredMixin, ListView):
    template_name = "imports/batch_list.html"
    paginate_by = 20

    def get_queryset(self):
        return ImportBatch.objects.select_related("uploaded_by")


class UploadView(CoordinatorRequiredMixin, View):
    template_name = "imports/upload.html"

    def get(self, request):
        return render(request, self.template_name, {"form": UploadForm()})

    def post(self, request):
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                batch = services.stage_upload(
                    form.cleaned_data["file"],
                    request.user,
                    contact_sheet=form.cleaned_data["contact_sheet"],
                    status_sheet=form.cleaned_data["status_sheet"],
                    use_status_sheet=form.cleaned_data["use_status_sheet"],
                )
            except (parsing.ParseError, services.ImportProblem) as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, f"Staged {batch.rows.count()} rows. Nothing has been imported yet.")
                return redirect("imports:mapping", pk=batch.pk)
        return render(request, self.template_name, {"form": form})


class BatchMixin(CoordinatorRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        self.batch = get_object_or_404(ImportBatch, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def require_staged(self):
        if not self.batch.is_staged:
            messages.error(self.request, "This batch is no longer staged.")
            return redirect("imports:detail", pk=self.batch.pk)
        return None


class MappingView(BatchMixin, View):
    template_name = "imports/mapping.html"

    def context(self, form):
        samples = list(self.batch.rows.order_by("row_number")[:5])
        return {
            "batch": self.batch,
            "form": form,
            "samples": samples,
            "previous": services.previous_commits(self.batch),
        }

    def get(self, request, pk):
        if response := self.require_staged():
            return response
        form = MappingForm(headers=self.batch.headers, initial=self.batch.column_mapping)
        return render(request, self.template_name, self.context(form))

    def post(self, request, pk):
        if response := self.require_staged():
            return response
        form = MappingForm(request.POST, headers=self.batch.headers)
        if not form.is_valid():
            return render(request, self.template_name, self.context(form))
        with transaction.atomic():
            self.batch.column_mapping = {k: v for k, v in form.cleaned_data.items() if v}
            self.batch.mapping_confirmed = True
            self.batch.caller_column_confirmed = False
            self.batch.save(update_fields=["column_mapping", "mapping_confirmed", "caller_column_confirmed"])
            log_event(
                request.user,
                "import.mapping",
                f"Batch #{self.batch.pk} mapping confirmed",
                self.batch,
                mapping=self.batch.column_mapping,
            )
            services.validate_batch(self.batch)
        return redirect("imports:detail", pk=self.batch.pk)


class BatchDetailView(BatchMixin, View):
    """Preview (staged) or import summary (committed)."""

    template_name = "imports/detail.html"

    def get(self, request, pk, commit_form=None):
        batch = self.batch
        if batch.is_staged and not batch.mapping_confirmed:
            return redirect("imports:mapping", pk=batch.pk)
        rows = batch.rows.select_related("link_contact", "contact").order_by("row_number")
        status_filter = request.GET.get("status", "")
        if status_filter in RowStatus.values:
            rows = rows.filter(status=status_filter)
        page = Paginator(rows, 50).get_page(request.GET.get("page"))
        all_rows = list(batch.rows.all())
        callers = list(callers_queryset().order_by("first_name", "username"))
        resolver = services.CallerResolver(batch)
        caller_names = []
        for name, count in services.caller_name_counts(all_rows):
            user, state = resolver.resolve(name)
            caller_names.append(
                {
                    "name": name,
                    "count": count,
                    "user": user,
                    "state": state,
                    "choice": (batch.caller_mapping or {}).get(services.normalize_name(name), ""),
                }
            )
        context = {
            "batch": batch,
            "page": page,
            "status_filter": status_filter,
            "statuses": RowStatus.choices,
            "counts": batch.summary.get("counts", {}),
            "caller_names": caller_names,
            "callers": callers,
            "status_records": services.status_record_rows(batch),
            "unmatched_callers": services.unmatched_callers(batch) if batch.is_staged else [],
            "review": services.review_summary(batch),
            "blockers": services.commit_blockers(batch) if batch.is_staged else [],
            "commit_form": commit_form
            or CommitForm(needs_ack=bool(batch.discrepancies), initial={"cycle": batch.cycle}),
            "result": batch.summary.get("result"),
            "previous": services.previous_commits(batch),
            "warning_count": sum(1 for r in all_rows if r.status == RowStatus.WARNING),
        }
        return render(request, self.template_name, context)


class CallerMappingView(BatchMixin, View):
    def post(self, request, pk):
        if response := self.require_staged():
            return response
        form = CallerMappingForm(request.POST)
        if form.is_valid():
            services.set_caller_mapping(
                self.batch,
                form.cleaned_data["name"],
                form.cleaned_data["choice"],
                request.user,
                save_alias=form.cleaned_data["save_alias"],
            )
            messages.success(request, "Caller mapping saved and rows revalidated.")
        else:
            messages.error(request, "; ".join(e for errors in form.errors.values() for e in errors))
        return redirect("imports:detail", pk=pk)


class CreateCallersView(BatchMixin, View):
    """Create Caller-only accounts for unmatched workbook names, then show the passwords once.

    The credentials page is rendered directly (not redirected) and marked no-store, so the
    plain-text passwords are never saved on the server or in the browser cache.
    """

    def post(self, request, pk):
        if response := self.require_staged():
            return response
        entries = []
        for index in request.POST.getlist("create"):
            name = request.POST.get(f"name_{index}", "")
            username = request.POST.get(f"username_{index}", "")
            if name:
                entries.append((name, username))
        try:
            created = services.create_callers_from_workbook(self.batch, entries, request.user)
        except services.ImportProblem as exc:
            messages.error(request, f"No accounts were created: {exc}")
            return redirect("imports:detail", pk=pk)
        response = render(
            request,
            "imports/callers_created.html",
            {
                "batch": self.batch,
                "created": created,
                "login_url": request.build_absolute_uri(reverse("accounts:login")),
            },
        )
        add_never_cache_headers(response)
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        return response


class RowEditView(BatchMixin, View):
    template_name = "imports/row_edit.html"

    def get_row(self, row_id):
        return get_object_or_404(ImportRow, batch=self.batch, pk=row_id)

    def candidates(self, row):
        return Contact.objects.filter(pk__in=row.candidate_ids)

    def render_form(self, request, row, form):
        return render(
            request,
            self.template_name,
            {
                "batch": self.batch,
                "row": row,
                "form": form,
                "candidates": self.candidates(row),
                "mapping": self.batch.column_mapping,
            },
        )

    def get(self, request, pk, row_id):
        if response := self.require_staged():
            return response
        row = self.get_row(row_id)
        initial = {
            **row.overrides,
            "action": row.action,
            "link_contact": row.link_contact_id,
            "skip_reason": row.skip_reason,
        }
        return self.render_form(request, row, RowForm(initial=initial, candidates=self.candidates(row)))

    def post(self, request, pk, row_id):
        if response := self.require_staged():
            return response
        row = self.get_row(row_id)
        form = RowForm(request.POST, candidates=self.candidates(row))
        if not form.is_valid():
            return self.render_form(request, row, form)
        services.update_row(
            row,
            overrides=form.overrides(),
            action=form.cleaned_data["action"],
            link_contact=form.cleaned_data["link_contact"],
            skip_reason=form.cleaned_data["skip_reason"],
            actor=request.user,
        )
        row.refresh_from_db()
        messages.success(request, f"Row {row.row_number} saved: {row.get_status_display()}.")
        remaining = self.batch.rows.filter(status=RowStatus.NEEDS_RESOLUTION).exists()
        suffix = f"?status={RowStatus.NEEDS_RESOLUTION}" if remaining else ""
        return redirect(reverse("imports:detail", args=[self.batch.pk]) + suffix)


class CommitView(BatchDetailView):
    def post(self, request, pk):
        if response := self.require_staged():
            return response
        batch = self.batch
        form = CommitForm(request.POST, needs_ack=bool(batch.discrepancies))
        if not form.is_valid():
            return self.get(request, pk, commit_form=form)
        try:
            with transaction.atomic():
                cycle = form.cleaned_data["cycle"]
                if cycle is None:
                    cycle = create_cycle(
                        name=form.cleaned_data["new_cycle_name"],
                        start_date=form.cleaned_data["new_cycle_start"],
                        planned_end_date=form.cleaned_data["new_cycle_end"],
                        actor=request.user,
                    )
                batch.cycle = cycle
                batch.caller_column_confirmed = True
                batch.discrepancies_acknowledged = bool(form.cleaned_data["acknowledge_discrepancies"])
                batch.save(update_fields=["cycle", "caller_column_confirmed", "discrepancies_acknowledged"])
                services.commit_batch(batch, request.user)
        except (services.ImportProblem, AllocationError) as exc:
            ImportBatch.objects.filter(pk=batch.pk).update(last_error=str(exc))
            messages.error(request, f"Nothing was imported: {exc}")
            return redirect("imports:detail", pk=pk)
        messages.success(request, "Import complete.")
        return redirect("imports:detail", pk=pk)


class CancelView(BatchMixin, View):
    def post(self, request, pk):
        try:
            services.cancel_batch(self.batch, request.user)
        except services.ImportProblem as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Batch cancelled. Nothing was imported.")
        return redirect("imports:list")


class RowReportView(BatchMixin, View):
    """CSV of every row with its status, issues and outcome (no phone numbers)."""

    def get(self, request, pk):
        rows = self.batch.rows.select_related("contact").order_by("row_number")
        data = [
            [
                r.row_number,
                r.values.get("full_name", ""),
                r.values.get("area", ""),
                r.values.get("caller_name", ""),
                r.get_status_display(),
                r.get_outcome_display() if r.outcome else "",
                "; ".join(i["message"] for i in r.issues),
                r.skip_reason,
                r.contact_id or "",
            ]
            for r in rows
        ]
        log_event(
            request.user, "export.import_rows", f"Exported row report for batch #{self.batch.pk}", self.batch
        )
        return csv_response(
            f"import-{self.batch.pk}-rows",
            [
                "Row",
                "Name",
                "Area",
                "Caller (workbook)",
                "Status",
                "Outcome",
                "Issues",
                "Skip reason",
                "Contact ID",
            ],
            data,
        )
