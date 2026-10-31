from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View


class BlessingSeenView(View):
    """ "Begin Sewa" on the daily blessing message: don't show it again today."""

    def post(self, request):
        request.user.blessing_shown_on = timezone.localdate()
        request.user.save(update_fields=["blessing_shown_on"])
        target = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(
            target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            target = "core:home"
        return redirect(target)
