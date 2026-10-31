from django.utils import timezone


def roles(request):
    """Role flags for navigation. Display only — views enforce access themselves."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"is_caller": False, "is_coordinator": False, "is_stall_lead": False}
    context = {
        "is_caller": user.is_caller,
        "is_coordinator": user.is_coordinator,
        "is_stall_lead": user.is_stall_lead,
        # The Sewa blessing message, once a day, for everyone who calls or coordinates.
        "show_blessing": user.has_any_role and user.blessing_shown_on != timezone.localdate(),
    }
    if user.is_coordinator:
        from apps.caller_requests.services import pending_count

        context["pending_requests"] = pending_count()
    return context
