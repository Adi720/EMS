"""Shapes for the Charts page: ring (pie) segments, week columns and per-caller bars.

Everything is computed here so the templates only draw. Rings use an SVG circle whose
circumference is 100, so a slice's length is simply its percentage.
"""

import math

RING_GAP = 1.2  # surface gap between slices, in % of the ring


def ring(parts, gap=RING_GAP):
    """parts: [(key, label, value)] in display order → {"total", "segments"}.

    Each segment has its share (``pct``) and, when non-zero, the SVG ``dash`` and ``offset``.
    """
    total = sum(value for _, _, value in parts)
    non_zero = sum(1 for _, _, value in parts if value)
    segments, start = [], 0.0
    for key, label, value in parts:
        share = 100 * value / total if total else 0
        segment = {"key": key, "label": label, "value": value, "pct": round(share)}
        if value:
            length = max(share - (gap if non_zero > 1 else 0), 0.4)
            segment["dash"] = f"{length:.2f} {100 - length:.2f}"
            segment["offset"] = f"{-start:.2f}"
        segments.append(segment)
        start += share
    return {"total": total, "segments": segments}


def nice_max(value):
    """A round axis maximum at or above ``value`` (5, 10, 20, 25, 50, 100, …)."""
    if value <= 5:
        return 5
    magnitude = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * magnitude:
            return int(step * magnitude)
    return int(10 * magnitude)


def week_columns(weeks):
    """Two one-series column charts from metrics rows (oldest first):
    % of calls made (fixed 0–100 axis) and number of Yes (its own axis)."""
    top = nice_max(max((w["yes"] for w in weeks), default=0))
    made, yes = [], []
    for w in weeks:
        day = w["session_obj"].session_date
        rate = w["completion_rate"] or 0
        made.append(
            {
                "day": day,
                "height": rate,
                "value": f"{rate}%",
                "tip": f"{day.day} {day:%b}: {w['completed']} of {w['assigned']} calls made ({rate}%)",
            }
        )
        yes.append(
            {
                "day": day,
                "height": round(100 * w["yes"] / top),
                "value": str(w["yes"]),
                "tip": f"{day.day} {day:%b}: {w['yes']} Yes of {w['assigned']} Saints",
            }
        )
    return {"made": made, "yes": yes, "yes_top": top, "yes_mid": top // 2}


def result_parts(row):
    """A metrics row as chart parts. "Unknown" is shown as its two halves: tried but
    not connected, and not called yet (they need different follow-up)."""
    not_called = row["not_attempted"]
    return [
        ("yes", "Yes", row["yes"]),
        ("not_possible", "Not Possible", row["not_possible"]),
        ("will_try", "Will Try", row["will_try"]),
        ("not_connected", "Call Not Connected", row["unknown"] - not_called),
        ("not_called", "Calls Not Made", not_called),
    ]


def caller_bars(rows):
    """Per-caller result bars, best first (calls made %, then Yes)."""
    bars = []
    for row in rows:
        assigned = row["assigned"] or 1
        parts = result_parts(row)
        bars.append(
            {
                "caller": row["caller_obj"],
                "assigned": row["assigned"],
                "completed": row["completed"],
                "rate": row["completion_rate"] or 0,
                "yes": row["yes"],
                "parts": [
                    {"key": k, "label": label, "value": v, "width": 100 * v / assigned}
                    for k, label, v in parts
                    if v
                ],
            }
        )
    return sorted(bars, key=lambda b: (-b["rate"], -b["yes"], str(b["caller"]).lower()))
