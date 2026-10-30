"""Settings shared by every environment.

All environment-specific values come from environment variables (or a local
``.env`` file that is never committed). See ``.env.example``.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# Path of the Django Admin, configurable so it is not exposed at a guessable URL.
ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "axes",
    "apps.core",
    "apps.accounts",
    "apps.audit",
    "apps.contacts",
    "apps.allocations",
    "apps.calling",
    "apps.reports",
    "apps.imports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Deny by default: every view requires login unless marked @login_not_required.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Must be last so it sees authentication failures.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.roles",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Authentication -------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# Inactivity timeout: the session expiry is pushed forward on every request.
SESSION_COOKIE_AGE = env.int("SESSION_IDLE_TIMEOUT_SECONDS", default=2 * 60 * 60)
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Login throttling (django-axes): lock a username+IP pair after repeated failures.
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = timedelta(hours=1)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "accounts/locked_out.html"

# --- Security headers (production tightens these further) ----------------

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

from django.contrib.messages import constants as message_constants  # noqa: E402

MESSAGE_TAGS = {message_constants.ERROR: "danger"}

# --- Business configuration -------------------------------------------------

# Default country for phone numbers without a country code (assumption A-1).
PHONE_DEFAULT_REGION = env("PHONE_DEFAULT_REGION", default="IN")
# Length of an allocation cycle, used to suggest the next cycle's dates.
ALLOCATION_CYCLE_MONTHS = env.int("ALLOCATION_CYCLE_MONTHS", default=3)
# Show "rotation due" on the coordinator dashboard this many days before a cycle ends.
ROTATION_REMINDER_DAYS = env.int("ROTATION_REMINDER_DAYS", default=14)
# Workbook import limits.
IMPORT_MAX_UPLOAD_BYTES = env.int("IMPORT_MAX_UPLOAD_BYTES", default=5 * 1024 * 1024)
IMPORT_MAX_ROWS = env.int("IMPORT_MAX_ROWS", default=5000)
FILE_UPLOAD_MAX_MEMORY_SIZE = IMPORT_MAX_UPLOAD_BYTES

# --- Email and weekly reminders --------------------------------------------

# e.g. smtp+tls://user%40gmail.com:app-password@smtp.gmail.com:587 ; default prints to the console.
vars().update(env.email_url("EMAIL_URL", default="consolemail://"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="EMS Seva <noreply@localhost>")
# Public address of the site, used for links in reminder emails.
SITE_URL = env("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")
# Day the reminder command acts (Monday=0 … Saturday=5) and whether it also starts calling.
REMINDER_WEEKDAY = env.int("REMINDER_WEEKDAY", default=5)
REMINDER_AUTO_START = env.bool("REMINDER_AUTO_START", default=True)

# --- Internationalisation -------------------------------------------------

LANGUAGE_CODE = "en-gb"
TIME_ZONE = env("TIME_ZONE", default="Asia/Kolkata")
USE_I18N = True
USE_TZ = True

# --- Static files ---------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Logging --------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
