from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.views.decorators.http import require_GET


def home(request):
    """Send each user to the dashboard for their role."""
    user = request.user
    if user.is_coordinator:
        return redirect("core:coordinator_dashboard")
    if user.is_caller:
        return redirect("core:caller_dashboard")
    if user.is_stall_lead:
        return redirect("contacts:stall_add")
    return render(request, "core/no_role.html", status=403)


@login_not_required
@require_GET
def manifest(request):
    """Lets phones install the site as an app (no address bar, own icon). Public: phones
    fetch it from the login page, and it holds nothing but the name and icons."""
    icon = "image/png"
    data = {
        "id": "/",
        "name": "EMS Seva",
        "short_name": "EMS Seva",
        "description": "Calling Seva for the EMS team",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#0f766e",
        "theme_color": "#0f766e",
        "icons": [
            {"src": static("img/icons/icon-192.png"), "sizes": "192x192", "type": icon, "purpose": "any"},
            {"src": static("img/icons/icon-512.png"), "sizes": "512x512", "type": icon, "purpose": "any"},
            {
                "src": static("img/icons/maskable-512.png"),
                "sizes": "512x512",
                "type": icon,
                "purpose": "maskable",
            },
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json")


@login_not_required
@require_GET
def healthz(request):
    """Unauthenticated liveness check for the hosting platform. Reveals nothing."""
    return HttpResponse("ok", content_type="text/plain")
