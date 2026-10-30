"""Spreadsheet-safe CSV and XLSX responses.

Text cells that a spreadsheet would treat as a formula (leading ``= + - @``,
tab or carriage return) are prefixed with an apostrophe so they display as
text instead of executing.
"""

import csv
import io
from datetime import date, datetime

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int | float):
        return value
    if isinstance(value, datetime):
        return timezone.localtime(value).replace(tzinfo=None) if timezone.is_aware(value) else value
    if isinstance(value, date):
        return value
    text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def _csv_text(value):
    value = safe_cell(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return value


def csv_response(filename, headers, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([_csv_text(h) for h in headers])
    for row in rows:
        writer.writerow([_csv_text(v) for v in row])
    # BOM so Excel opens UTF-8 names correctly.
    response = HttpResponse("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    return response


def xlsx_response(filename, headers, rows, sheet_title="Report"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title[:31]
    sheet.append([safe_cell(h) for h in headers])
    for row in rows:
        sheet.append([safe_cell(v) for v in row])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, datetime):
                cell.number_format = "yyyy-mm-dd hh:mm"
            elif isinstance(cell.value, date):
                cell.number_format = "yyyy-mm-dd"
            elif isinstance(cell.value, str):
                cell.data_type = "s"  # never let openpyxl infer a formula
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response


def export_response(fmt, filename, headers, rows, sheet_title="Report"):
    if fmt == "xlsx":
        return xlsx_response(filename, headers, rows, sheet_title)
    return csv_response(filename, headers, rows)
