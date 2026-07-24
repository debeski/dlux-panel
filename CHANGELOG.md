# Changelog

## v0.1.2
- **Manifest-Sourced Version**: Bumped DjangoLux to 1.5.3 and adopted `dlux.utils.get_project_version`, making `release-manifest.json` the single version source; retired the root `VERSION` file and simplified the release validator to a manifest-vs-tag check.
- **Baked DjangoLux Version In Release Manifest**: `validate_project_release_manifest.py` now resolves the pinned `django-lux` version via `resolve_pinned_dlux_version()` and injects `baked_dlux_version` into the published manifest label, emitting a `dlux_version` output that replaces the workflow's `grep` step for `DLUX_BAKED_VERSION`. Added `tests/test_release_manifest.py` (8 tests).

## v0.1.1
- **Pairing-First Enrollment UX**: The enrollment-token page now surfaces the control-panel URL alongside the one-use token and directs operators to paste both into the target app's DjangoLux *Control Panel* tile (UI pairing, no redeploy), keeping `COMPOSER_CONTROL_URL`/`COMPOSER_ENROLLMENT_TOKEN` as the documented headless fallback. `EnrollmentTokenView` passes `control_url` from the request.

## v0.1.0
- **Control Plane Foundation**: Added scoped fleet models/UI, hashed enrollment and bearer credentials, Uvicorn-served ASGI long polling, monotonic events, snapshot replacement, controlled batches, two-phase rotation/revocation, central backup creation, and audited recovery deployment.
- **Operational Guardrails**: Added 90-day sanitized-log retention, 50-agent concurrency coverage, native DLUX scope/permission checks, forbidden-action rejection, and the panel's own generated Composer agent topology.
