from functools import cached_property

from django.contrib.auth.models import AbstractUser

from .roles import Role


class User(AbstractUser):
    """Application user. Kept as a custom model so fields can be added later."""

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
    def has_any_role(self):
        return self.is_caller or self.is_coordinator
