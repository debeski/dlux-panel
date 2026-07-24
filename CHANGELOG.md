# Changelog

## v0.1.4
- **Restored Application Version Reporting**: Adopting `release-manifest.json` in v0.1.2 retired the root `VERSION` file that DjangoLux's `app_version()` reads, so the Updates card reported no version. `config/settings.py` now sets `DLUX_APP_VERSION = get_project_version(BASE_DIR)`, keeping the manifest as the single source.
- **Single Image Reference**: Added `WEB_IMAGE=debeski/dlux-panel:latest` to `.secrets/.env` and corrected the two `composer-agent` fallbacks that still read `dlux_control:latest`, which made the agent poll an image published in no registry so no update was ever discovered.

## v0.1.3
- **Single-Page Panel On Native Dlux Primitives**: Replaced the hand-rolled `<table>` and the separate detail/form pages with one `FleetOverviewView` built on `SingleTableMixin`/`FilterView`. New `ManagedProjectTable(DluxTable)` supplies badge columns plus a permission-gated row context menu whose every entry opens a Dlux dynamic modal — view (double-click), edit via the generic `modal_manager`, update, backup, restart, enrollment, rotate, revoke, and recovery. New `ManagedProjectFilter` adds search/environment/agent-state filtering, and pagination, per-page, and resizable columns now come from `DluxTable`. Project add/edit reuses `modal_manager`, so `project_add`/`project_edit` routes and `project_form.html` are retired to `.xpose/`.
- **Modal Endpoints With Non-JS Fallbacks**: Detail, action, enrollment, and batch views return `{"html": …}` for the modal's `X-Requested-With` fetches and `{"success": true, "refresh_parent": true}` on completion, while plain navigation keeps the previous page/redirect behaviour so every route still works without JavaScript. Page templates are now thin shells including the same partials.
- **Live In-Flight Operations Strip**: New `ActiveOperationsView` feed plus a strip on the overview keeps queued/running operations visible after their modal closes; `fleet.js` polls the feed and still advances operation rows inside an open modal. Deep links via `/fleet/?project=<uuid>` resolve through the scoped queryset and auto-open that project's modal.
- **Canonical HTTPS Pairing URL**: `EnrollmentTokenView` now copies the configured `BASE_URL` instead of reconstructing the control-panel URL from the internal HTTP request after TLS termination, preserving `https://dlux.eidc.gov.ly` for project enrollment.
- **Scaffold Settings Check**: Made the settings import assertion accept grouped `dlux.utils` imports while still requiring `dlux_settings`.

## v0.1.2
- **Manifest-Sourced Version**: Bumped DjangoLux to 1.5.3 and adopted `dlux.utils.get_project_version`, making `release-manifest.json` the single version source; retired the root `VERSION` file and simplified the release validator to a manifest-vs-tag check.
- **Baked DjangoLux Version In Release Manifest**: `validate_project_release_manifest.py` now resolves the pinned `django-lux` version via `resolve_pinned_dlux_version()` and injects `baked_dlux_version` into the published manifest label, emitting a `dlux_version` output that replaces the workflow's `grep` step for `DLUX_BAKED_VERSION`. Added `tests/test_release_manifest.py` (8 tests).

## v0.1.1
- **Pairing-First Enrollment UX**: The enrollment-token page now surfaces the control-panel URL alongside the one-use token and directs operators to paste both into the target app's DjangoLux *Control Panel* tile (UI pairing, no redeploy), keeping `COMPOSER_CONTROL_URL`/`COMPOSER_ENROLLMENT_TOKEN` as the documented headless fallback. `EnrollmentTokenView` passes `control_url` from the request.

## v0.1.0
- **Control Plane Foundation**: Added scoped fleet models/UI, hashed enrollment and bearer credentials, Uvicorn-served ASGI long polling, monotonic events, snapshot replacement, controlled batches, two-phase rotation/revocation, central backup creation, and audited recovery deployment.
- **Operational Guardrails**: Added 90-day sanitized-log retention, 50-agent concurrency coverage, native DLUX scope/permission checks, forbidden-action rejection, and the panel's own generated Composer agent topology.
