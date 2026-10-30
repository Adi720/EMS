import json

from django.core.serializers.json import DjangoJSONEncoder

from .models import AuditEvent


def _jsonable(details):
    return json.loads(json.dumps(details, cls=DjangoJSONEncoder))


def log_event(actor, action, summary, obj=None, **details):
    """Record an audit event. Do not put phone numbers in ``details``."""
    return AuditEvent.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        object_type=obj._meta.label_lower if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        summary=summary[:255],
        details=_jsonable(details),
    )


def events_for(obj):
    return AuditEvent.objects.filter(object_type=obj._meta.label_lower, object_id=str(obj.pk))
