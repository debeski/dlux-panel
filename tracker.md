# Project Tracker (dlux-control)

## Part 1: Project Related
### Current Verified Snapshot:
- Dedicated DjangoLux fleet control panel (v0.2.2 tagged; v0.2.3 on branch `0.2/worker_restart_service`, unmerged; DjangoLux 1.5.9) has native scoped fleet UI and its own generated `composer-agent`.
- Schema-v1 API runs under Uvicorn/ASGI and implements hashed enrollment/auth, long polls, monotonic events, snapshots, local reconciliation, capabilities, rotation, and revocation.
- Typed actions cover DLUX image update/backup creation, safe restart, and audited recovery; remote restore/arbitrary execution are absent.
- DLUX provides configurable human-login/OTP throttles and mandatory TOTP; HAProxy now sets X-Forwarded-Proto/For across the deployed projects.
- Live capture confirms pfSense/HAProxy reaches the panel VM from `192.168.20.1` and Docker preserves that source through Caddy ingress.

### Current Project Adopted Standards:
- Use native DjangoLux scopes, groups, permissions, activity logging, translations, and backend authorization.
- Agent machine credentials are independent from human authentication and are stored only as password hashes.

### Adopted Standards' rules and policies:
- Agent API lives at `/api/agent/v1/`; long polling is served by ASGI.
- Never add arbitrary remote shell, restore, down, purge, build, or database actions.

### Cross-Cutting Audits if any:
- 50 simultaneous one-second ASGI long polls complete in about 1.6 seconds in the test environment.
- 2026-07-26 security review covered panel/agent auth, HAProxy→Caddy trust, public routes, Docker authority, defaults, and Composer's unresolved audit findings.

### Current Project's Unsolved Known Bugs:
- Live Docker/network and control-panel self-update acceptance still require staging infrastructure.
- Deployed stacks created before the `WEB_IMAGE` change still check `dlux_control:latest`; `docker compose up -d` (not `restart`) is required to recreate the agent with the registry image name.
- Legacy pgAdmin removal is in progress, and Caddy still publicly serves `/_update/log.txt`.
- Deploy `CADDY_TRUSTED_PROXIES=192.168.20.1/32`; machine-API limits and backend firewall isolation still need live verification.
- Composer still has mutable image refs and host-root-equivalent POST-enabled Docker API authority.

### Incomplete Tasks:
- **Priority 1:**
  - [ ] Complete pgAdmin removal and restrict the public deploy-log route.
  - [ ] Publish/deploy Composer v1.2.8 and reduce Docker API authority before expanding production control.
  - [ ] Set deployed `CADDY_TRUSTED_PROXIES=192.168.20.1/32`; verify machine-API limits and backend firewall isolation live.
  - [ ] Run staging end-to-end update and outage/replay matrix.
  - [ ] Enroll and self-update the control panel after initial administrative setup.
  - [ ] Pilot one noncritical project before Decrees and Trademarks.
- **Priority 2:**
  - [ ] Owner OK to merge `0.2/worker_restart_service` (v0.2.3, `worker` restart choice for DjangoLux 1.16 stacks); not pushed.
  - [ ] Pin forms to DjangoLux 1.5.9 and pair it via `/sys/control-panel/`.
  - [ ] Export `ENV DLUX_BAKED_VERSION` in Dockerfile(s) so runtime `get_baked_version()` stops reporting the activated version as baked.
  - [ ] Enroll the control panel's own agent in staging.
  - [ ] Add separate SSO project after the fleet deployment path stabilizes.
  - [ ] Browser-validate single-title fleet modals and persistent action footers; the in-app browser had no active session.
- **Completed Recently:**
  - [x] v0.2.3 (branch only): safe restart offers `worker` beside `celery`; a service outside the agent's `COMPOSER_AGENT_RESTART_SERVICES` fails with Composer's reason in the operation history.
  - [x] Fleet AJAX partials now rely on one DjangoLux shell title/body/footer and explicitly pin submit/cancel/Done action bars in the persistent footer.
  - [x] Composer v1.2.8 coalesces unsent snapshots to the latest value and collapses existing backlogs at startup.
  - [x] Replaced button-like enrollment values with selectable read-only inputs and made clipboard rejection fall back to legacy copy.
  - [x] Made project secrets fail closed in production, set `.secrets/.env` to 0600, and added strict configurable Caddy proxy trust.
  - [x] Composer v1.2.7 pins enrolled control URLs and rejects credentialed redirects.
  - [x] HAProxy now supplies X-Forwarded-Proto and X-Forwarded-For for this panel and the other deployed projects.
  - [x] Table/cards overview toggle via dlux Options (`fleet/dlux_options.py` card + settings tile, `fleet/layouts.py` resolver); cards reuse the row context menu.
  - [x] Operation observability: feed/status expose phase, last-event age, overdue, agent online/last-seen; strip renders them; `expire_stale_operations` beat task auto-fails stuck ops past `deadline_at`+grace; add/edit/enrollment modals refresh the table.
  - [x] Localized the whole fleet panel en/ar via `fleet/translations.py` (per-request header/badge relabel); added form-only project modal (`show_table=False`) and click-to-copy enrollment fields.
  - [x] Rebuilt the panel as one page on `DluxTable`/`FilterView` with a dynamic-modal row context menu, retiring the detail/form pages and `project_add`/`project_edit` routes.
  - [x] v0.1.3 enrollment pages copy canonical `BASE_URL`, preserving the public HTTPS origin across the internal HTTP proxy hop.
  - [x] Implemented fleet models/migration, scoped UI/actions, agent API, controlled batches, backup inspection, retention, and immutable break-glass audit.
  - [x] Added identical protocol fixtures and 13 control tests including three-wide batches and 50-agent ASGI concurrency.
  - [x] Added tag-driven release: `release-manifest.json`, `.github/workflows/release.yml` (image `debeski/dlux-panel`), and `tools/validate_project_release_manifest.py`.
  - [x] Adopted DjangoLux 1.5.3 `get_project_version`: `release-manifest.json` is the sole version source; retired root `VERSION` (→ `.xpose/VERSION`); validator now checks manifest==tag only.
  - [x] Landed `baked_dlux_version` end-to-end: validator injects it from the requirements pin (replacing the workflow grep), composer v1.2.3 + dlux v1.5.4 pass it through, dlux renders a "baked dlux" badge in the image-update review modal.
  - [x] Prepared Dlux 1.5.6 visible pairing validation and Archive v1.1.7 with the corrected target pin.

### One-line info about last verified Tests:
- 2026-11-11: panel 57/57 GREEN on DjangoLux v1.5.9 source (`PYTHONPATH=<v1.5.9 export>`); `DEBUG_STATUS=False` now also needs `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` test values.

### One-line info about last time edited Docs:
- 2026-11-11: operations documents the `worker`/`celery` restart choices and the agent's allowlist refusal.

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
