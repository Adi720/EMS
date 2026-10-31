"""Production static files: every url() / source map referenced by CSS and JS must exist,
otherwise `collectstatic` with manifest storage fails at deploy time."""

from io import StringIO

from django.core.management import call_command
from django.test import override_settings


def test_collectstatic_with_manifest_storage(tmp_path):
    storages = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    with override_settings(STATIC_ROOT=tmp_path, STORAGES=storages):
        call_command("collectstatic", interactive=False, verbosity=0, stdout=StringIO())
    assert (tmp_path / "staticfiles.json").exists()
    assert list((tmp_path / "vendor" / "bootstrap-icons" / "fonts").glob("bootstrap-icons.*.woff2"))
    assert list((tmp_path / "vendor" / "inter" / "files").glob("inter-latin-wght-normal.*.woff2"))
