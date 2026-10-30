from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET


def home(request):
    """Send each user to the dashboard for their role."""
    user = request.user
    if user.is_coordinator:
        return redirect("core:coordinator_dashboard")
    if user.is_caller:
        return redirect("core:caller_dashboard")
    return render(request, "core/no_role.html", status=403)


@login_not_required
@require_GET
def healthz(request):
    """Unauthenticated liveness check for the hosting platform. Reveals nothing."""
    return HttpResponse("ok", content_type="text/plain")
