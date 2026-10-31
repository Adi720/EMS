"""Small presentation helpers for templates: icons, navigation state, numbers, names."""

from django import template
from django.utils import timezone
from django.utils.html import format_html

register = template.Library()

# Section shown in the top bar, by URL namespace or full view name.
SECTIONS = {
    "core:coordinator_dashboard": "Dashboard",
    "core:caller_dashboard": "My calls",
    "contacts": "Saints",
    "team": "Calling Team",
    "allocations": "Assignments",
    "calling": "EMS Congregations",
    "reports": "Reports",
    "imports": "Import",
    "audit": "Audit log",
    "caller_requests": "Requests",
    "caller_requests:mine": "Raise Request",
    "team:performance": "Performance",
    "core:my_report": "My Report",
    "contacts:stall_add": "Add Saint",
    "accounts": "Account",
}


@register.simple_tag
def icon(name, label="", extra_class=""):
    """Bootstrap Icon. Decorative unless a label is given (then announced to screen readers)."""
    classes = f"bi bi-{name} {extra_class}".strip()
    if label:
        return format_html('<i class="{}" role="img" aria-label="{}"></i>', classes, label)
    return format_html('<i class="{}" aria-hidden="true"></i>', classes)


def _match(resolver_match, target):
    if resolver_match is None:
        return False
    if ":" in target:
        return resolver_match.view_name == target
    return resolver_match.namespace == target


@register.simple_tag(takes_context=True)
def nav_is_active(context, *targets):
    """True when the current page belongs to any target ('contacts' or 'core:caller_dashboard')."""
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    if match and match.view_name == "calling:task_detail" and "core:caller_dashboard" in targets:
        return not getattr(request.user, "is_coordinator", False)
    return any(_match(match, target) for target in targets)


@register.simple_tag(takes_context=True)
def current_section(context):
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    if match is None:
        return ""
    if match.view_name == "calling:task_detail" and not request.user.is_coordinator:
        return "My calls"
    return SECTIONS.get(match.view_name) or SECTIONS.get(match.namespace, "")


@register.filter
def initials(user):
    names = [user.first_name, user.last_name] if (user.first_name or user.last_name) else [user.username]
    letters = "".join(part.strip()[:1] for part in names if part and part.strip())
    return (letters or "?")[:2].upper()


@register.filter
def display_name(user):
    return user.get_full_name() or user.username


@register.simple_tag
def percent(value, total):
    """Whole-number percentage, 0 when there is nothing to divide by."""
    try:
        value, total = float(value or 0), float(total or 0)
    except (TypeError, ValueError):
        return 0
    return round(100 * value / total) if total else 0


@register.simple_tag
def greeting():
    hour = timezone.localtime().hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"
