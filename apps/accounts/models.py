from functools import cached_property

from django.contrib.auth.models import AbstractUser
from django.db import models

from .roles import Role


class User(AbstractUser):
    """Application user. Kept as a custom model so fields can be added later."""

    on_leave_since = models.DateField(
        null=True, blank=True, help_text="Set while a caller is On Leave (taking a break from calling)."
    )
    blessing_shown_on = models.DateField(
        null=True, blank=True, help_text="Last day the Sewa blessing message was shown after login."
    )

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def __str__(self):
        return self.get_full_name() or self.username

    @cached_property
    def role_names(self):
        if not self.is_active:
            return frozenset()
        return frozenset(self.groups.filter(name__in=Role.ALL).values_list("name", flat=True))

    @property
    def is_caller(self):
        return Role.CALLER in self.role_names

    @property
    def is_coordinator(self):
        return self.is_active and (self.is_superuser or Role.COORDINATOR in self.role_names)

    @property
    def is_stall_lead(self):
        return Role.STALL_LEAD in self.role_names

    @property
    def is_on_leave(self):
        return self.on_leave_since is not None

    @property
    def has_any_role(self):
        return self.is_caller or self.is_coordinator or self.is_stall_lead
