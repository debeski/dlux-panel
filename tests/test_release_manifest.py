"""Release manifest validation and label injection."""

import base64
import json
import sys
from pathlib import Path

from django.test import SimpleTestCase

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from validate_project_release_manifest import (  # noqa: E402
    ProjectReleaseManifestError,
    encode_project_release_manifest_label,
    resolve_pinned_dlux_version,
    validate_project_release_manifest,
)

REPOSITORY = "debeski/dlux-control-panel"


def _manifest(tmp_path, **overrides):
    version = overrides.pop("version", "9.9.9")
    manifest = {
        "schema_version": 1,
        "version": version,
        "summary": "Summary",
        "highlights": ["One"],
        "release_url": f"https://github.com/{REPOSITORY}/releases/tag/v{version}",
        **overrides,
    }
    (tmp_path / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


class ReleaseManifestTests(SimpleTestCase):
    def test_committed_manifest_matches_its_own_release_url(self):
        manifest = json.loads(
            (PROJECT_ROOT / "release-manifest.json").read_text(encoding="utf-8")
        )
        validate_project_release_manifest(
            PROJECT_ROOT,
            tag=f"v{manifest['version']}",
            repository=REPOSITORY,
        )

    def test_committed_manifest_omits_injected_baked_version(self):
        """The baked version is a build-time fact, never hand-authored."""
        manifest = json.loads(
            (PROJECT_ROOT / "release-manifest.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("baked_dlux_version", manifest)

    def test_tag_mismatch_is_rejected(self):
        with self.assertRaises(ProjectReleaseManifestError):
            validate_project_release_manifest(
                PROJECT_ROOT, tag="v0.0.1", repository=REPOSITORY
            )

    def test_refs_tags_prefix_is_accepted(self):
        manifest = json.loads(
            (PROJECT_ROOT / "release-manifest.json").read_text(encoding="utf-8")
        )
        validate_project_release_manifest(
            PROJECT_ROOT,
            tag=f"refs/tags/v{manifest['version']}",
            repository=REPOSITORY,
        )

    def test_pinned_dlux_version_is_resolved_from_requirements(self):
        self.assertRegex(resolve_pinned_dlux_version(PROJECT_ROOT), r"^\d+\.\d+")

    def test_missing_dlux_pin_fails_the_release(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "requirements.txt").write_text("django-lux\nredis\n", encoding="utf-8")
            with self.assertRaises(ProjectReleaseManifestError):
                resolve_pinned_dlux_version(root)

    def test_extras_and_comments_do_not_defeat_pin_resolution(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "requirements.txt").write_text(
                "# django-lux==0.0.1\ndjango-lux[updater]==1.5.3  # pinned\n",
                encoding="utf-8",
            )
            self.assertEqual(resolve_pinned_dlux_version(root), "1.5.3")

    def test_label_round_trips_with_injected_baked_version(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = _manifest(root)

        published = {**manifest, "baked_dlux_version": "1.5.3"}
        label = encode_project_release_manifest_label(published)
        self.assertTrue(label.startswith("base64:"))
        payload = label.removeprefix("base64:")
        decoded = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode("utf-8")
        )
        self.assertEqual(decoded["baked_dlux_version"], "1.5.3")
        self.assertEqual(decoded["schema_version"], 1)
