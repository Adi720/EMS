"""Server-side role checks for views.

Login is already enforced globally by ``LoginRequiredMiddleware``; these mixins
add the role check and return 403 for authenticated users without the role.
Object-level scoping (a caller only seeing their own records) is done in each
view's queryset, never by filtering in templates.
"""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    raise_exception = False  # anonymous → login page; authenticated without role → 403

    def has_role(self, user):
        raise NotImplementedError

    def test_func(self):
        return self.has_role(self.request.user)


class CallerRequiredMixin(RoleRequiredMixin):
    def has_role(self, user):
        return user.is_caller


class CoordinatorRequiredMixin(RoleRequiredMixin):
    """Coordinators and system administrators."""

    def has_role(self, user):
        return user.is_coordinator
