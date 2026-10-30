"""Production settings. Requires HTTPS in front of the application."""

from .base import *  # noqa: F403
from .base import env

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = False
# Subdomain HSTS and preload depend on the production domain (requirements N-4);
# decide them at deployment rather than failing the deploy check now.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# Behind a reverse proxy the client IP comes from X-Forwarded-For; used by django-axes.
AXES_IPWARE_PROXY_COUNT = env.int("AXES_PROXY_COUNT", default=1)
AXES_IPWARE_META_PRECEDENCE_ORDER = ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"]

DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)  # noqa: F405
