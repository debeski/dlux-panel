"""
Generated with django-lux 1.4.15.
Project name: dlux_control.
Generated on: 2026-07-23.
"""
from pathlib import Path

from django.test import SimpleTestCase


class ProjectScaffoldTests(SimpleTestCase):
    def test_settings_uses_dlux_helper(self):
        settings_path = Path(__file__).resolve().parents[1] / "config" / "settings.py"
        contents = settings_path.read_text(encoding="utf-8")
        self.assertIn("from dlux.utils import dlux_settings", contents)
        self.assertIn("dlux_settings(globals())", contents)

    def test_urls_mount_dlux_at_root(self):
        urls_path = Path(__file__).resolve().parents[1] / "config" / "urls.py"
        contents = urls_path.read_text(encoding="utf-8")
        self.assertIn('path("", include("dlux.urls"))', contents)
