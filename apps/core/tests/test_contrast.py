"""WCAG contrast of the design tokens in static/css/tokens.css (both themes).

Text needs 4.5:1, large/secondary marks and form-field borders 3:1.
"""

import re
from pathlib import Path

import pytest

TOKENS = Path(__file__).resolve().parents[3] / "static" / "css" / "tokens.css"
CSS = TOKENS.read_text(encoding="utf-8")
_LIGHT = CSS.split('[data-bs-theme="dark"] {')[0]
_DARK = CSS.split('[data-bs-theme="dark"] {')[1].split("/* ---- Map tokens")[0]


def _tokens(block):
    return dict(re.findall(r"--ems-([\w-]+):\s*([^;]+);", block))


THEMES = {"light": _tokens(_LIGHT)}
THEMES["dark"] = {**THEMES["light"], **_tokens(_DARK)}


def _rgb(value, under=(255, 255, 255)):
    value = value.strip()
    if value.startswith("#"):
        return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))
    r, g, b, *alpha = (float(x) for x in re.findall(r"[\d.]+", value))
    a = alpha[0] if alpha else 1
    return tuple(round(a * c + (1 - a) * u) for c, u in zip((r, g, b), under, strict=True))


def _luminance(rgb):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(fg, bg):
    high, low = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


PAIRS = [
    ("text", "bg", 4.5), ("text", "surface", 4.5), ("muted", "surface", 4.5), ("muted", "surface-2", 4.5),
    ("muted", "bg", 4.5), ("accent-text", "surface", 4.5), ("on-accent", "accent", 4.5),
    ("success-text", "success-soft", 4.5), ("danger-text", "danger-soft", 4.5),
    ("warning-text", "warning-soft", 4.5), ("info-text", "info-soft", 4.5),
    ("neutral-text", "neutral-soft", 4.5), ("accent-text", "accent-soft", 4.5),
    ("nav-text", "nav-bg", 4.5), ("nav-muted", "nav-bg", 4.5),
    ("subtle", "surface", 3.0), ("input-border", "surface", 3.0), ("input-border", "bg", 3.0),
]  # fmt: skip


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize(("fg", "bg", "minimum"), PAIRS)
def test_token_contrast(theme, fg, bg, minimum):
    tokens = THEMES[theme]
    background = _rgb(tokens[bg], _rgb(tokens["surface"]))
    foreground = _rgb(tokens[fg], background)
    assert _ratio(foreground, background) >= minimum, f"{theme}: {fg} on {bg}"
