def roles(request):
    """Role flags for navigation. Display only — views enforce access themselves."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"is_caller": False, "is_coordinator": False}
    return {"is_caller": user.is_caller, "is_coordinator": user.is_coordinator}
