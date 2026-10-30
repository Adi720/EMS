"""Settings for the automated test suite.

Uses ``TEST_DATABASE_URL`` when set (CI uses PostgreSQL), otherwise ``DATABASE_URL``.
"""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-insecure-key")
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from .base import *  # noqa: E402, F403

DEBUG = False
ALLOWED_HOSTS = ["testserver"]

# Fast hashing keeps the suite quick; never use outside tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}
