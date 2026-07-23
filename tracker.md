# Project Tracker (dlux-control)

## Part 1: Project Related
### Current Verified Snapshot:
- Dedicated DjangoLux fleet control panel v0.1.0 has native scoped fleet UI and its own generated `composer-agent`.
- Schema-v1 API runs under Uvicorn/ASGI and implements hashed enrollment/auth, long polls, monotonic events, snapshots, local reconciliation, capabilities, rotation, and revocation.
- Typed actions cover DLUX image update/backup creation, safe restart, and audited recovery; remote restore/arbitrary execution are absent.

### Current Project Adopted Standards:
- Use native DjangoLux scopes, groups, permissions, activity logging, translations, and backend authorization.
- Agent machine credentials are independent from human authentication and are stored only as password hashes.

### Adopted Standards' rules and policies:
- Agent API lives at `/api/agent/v1/`; long polling is served by ASGI.
- Never add arbitrary remote shell, restore, down, purge, build, or database actions.

### Cross-Cutting Audits if any:
- 50 simultaneous one-second ASGI long polls complete in about 1.6 seconds in the test environment.

### Current Project's Unsolved Known Bugs:
- Live Docker/network and control-panel self-update acceptance still require staging infrastructure.

### Incomplete Tasks:
- **Priority 1:**
  - [ ] Run staging end-to-end update and outage/replay matrix.
  - [ ] Enroll and self-update the control panel after initial administrative setup.
  - [ ] Pilot one noncritical project before Decrees and Trademarks.
- **Priority 2:**
  - [ ] Enroll the control panel's own agent in staging.
  - [ ] Add separate SSO project after the fleet deployment path stabilizes.
- **Completed Recently:**
  - [x] Implemented fleet models/migration, scoped UI/actions, agent API, controlled batches, backup inspection, retention, and immutable break-glass audit.
  - [x] Added identical protocol fixtures and 13 control tests including three-wide batches and 50-agent ASGI concurrency.
  - [x] Added tag-driven release: `release-manifest.json`, `.github/workflows/release.yml` (image `debeski/dlux-panel`), and `tools/validate_project_release_manifest.py`.

### One-line info about last verified Tests:
- 2026-07-23: 13/13 fleet tests GREEN; migration drift/check GREEN; `docker compose config -q` GREEN.

### One-line info about last time edited Docs:
- 2026-07-23: operations.md gained a Releasing section for the tag-driven `debeski/dlux-panel` pipeline.

## Part 2: Global
### Global Standard Helpers, Shortcuts, Info, etc.:
- Use `PYTHONPATH=../pkg-django-lux ../pkg-django-lux/.venv/bin/python manage.py ...` for local package development.

### Global Rulesets:
- Preserve obsolete generated files under `.xpose/`; never delete project files.

### Agent Handoff Rules:
- Keep protocol fixtures synchronized with Composer and DjangoLux.
- Pre-release local `test.sqlite3` artifacts are preserved under `.xpose/20260723-agent-final-{2,3}/`; tests now use memory and these are not production state.
- The unused generated WSGI `gunicorn.py` is preserved under `.xpose/project-scaffold/`; production uses Uvicorn/ASGI.

### References and Links:
- Protocol documentation will live in `docs/agent-protocol-v1.md`.
