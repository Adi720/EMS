"""Application roles.

Roles are Django groups, created by migration ``0002_create_role_groups``.
System administrators are users with ``is_superuser``; they have every
coordinator capability plus Django Admin access.
"""


class Role:
    CALLER = "Caller"
    COORDINATOR = "Coordinator"
    # Adds new Saints from the stall; cannot assign callers or see call results.
    STALL_LEAD = "Stall Lead"

    ALL = (CALLER, COORDINATOR, STALL_LEAD)
