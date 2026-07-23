# Changelog

## v0.1.1
- **Pairing-First Enrollment UX**: The enrollment-token page now surfaces the control-panel URL alongside the one-use token and directs operators to paste both into the target app's DjangoLux *Control Panel* tile (UI pairing, no redeploy), keeping `COMPOSER_CONTROL_URL`/`COMPOSER_ENROLLMENT_TOKEN` as the documented headless fallback. `EnrollmentTokenView` passes `control_url` from the request.

## v0.1.0
- **Control Plane Foundation**: Added scoped fleet models/UI, hashed enrollment and bearer credentials, Uvicorn-served ASGI long polling, monotonic events, snapshot replacement, controlled batches, two-phase rotation/revocation, central backup creation, and audited recovery deployment.
- **Operational Guardrails**: Added 90-day sanitized-log retention, 50-agent concurrency coverage, native DLUX scope/permission checks, forbidden-action rejection, and the panel's own generated Composer agent topology.
