# Operations

## Front proxy (pfSense/HAProxy)

The TLS-terminating HAProxy frontend must overwrite `X-Forwarded-Proto` (action *http-request header set*, name `X-Forwarded-Proto`, fmt `https`, no condition) and append the client IP through **Use 'forwardfor' option**. These HAProxy settings are necessary but separate from Caddy's trust decision.

`CADDY_TRUSTED_PROXIES` is a Caddy/Compose variable, not a DjangoLux setting. Set it in `.secrets/.env` to the pfSense/HAProxy address as seen by Caddy, using a host CIDR such as `192.168.20.1/32`; use the actual address, not a client address from HAProxy statistics. The checked-in `private_ranges` default preserves existing deployments but is broader than a single proxy. Caddy also enables `trusted_proxies_strict`, which evaluates an appended `X-Forwarded-For` chain from right to left.

Allow the published Caddy backend port through the host firewall only from pfSense/HAProxy. After changing the variable, recreate Caddy so its environment is updated: `docker compose --env-file .secrets/.env up -d --force-recreate caddy`.

## Production secrets

This project requires `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, and `ADMIN_PASS` in its secrets file; Compose stops during interpolation if any is absent. Django settings also reject a missing Django or database secret whenever `DEBUG_STATUS=False`, while direct non-Compose development retains explicit development-only defaults. Keep the file private with `chmod 600 .secrets/.env`. These requirements apply only to this panel repository.

## Enrollment and availability

Create a `ManagedProject` in its native DLUX scope, then create an enrollment token from its project page. Tokens are single-use and expire after 15 minutes. The displayed control URL comes from the panel's canonical `BASE_URL`; production must set it to the public HTTPS origin, such as `https://dlux.eidc.gov.ly`, so an internal HTTP proxy hop cannot produce an invalid pairing URL. Paste that URL and token into the target application's `/sys/control-panel/` page. The resulting random bearer secret persists in that project's dedicated agent-state volume; the panel stores only its hash.

The shown control URL and token are selectable read-only inputs. Their copy buttons use the browser Clipboard API and fall back to a temporary selection when that API is unavailable or rejects the write.

Fleet AJAX partials provide body content only; the shared DjangoLux dynamic-modal shell owns the single title, close control, scrolling body, and persistent footer. Submit, cancel, generate-token, and Done action bars use `data-dlux-modal-footer`, so they remain visible while long forms and operation tables scroll.

Credential rotation is issued as a typed command. The server stages a pending hash, the agent persists the new secret in SQLite, confirms with it, and only then promotes it and revokes the old credential. Interrupted confirmations replay from durable state. Composer 1.2.7 pins the normalized control URL after enrollment and rejects redirects; changing panels requires revocation/re-enrollment or an explicit local reset of the agent-state volume. Revocation blocks central traffic immediately without disabling local DLUX updates.

## Updates, backups, and restart

A normal central update chooses data, full, or skipped backup and enters the same DLUX queue/lock as a local request. Terminal central success waits for DLUX finalization after Composer recreate and health checks. Backup rejection/failure prevents the Composer trigger.

Central backup creation supports data or full backups. The project-local DLUX backup engine owns artifacts and publishes approved status/history through snapshots. Restore stays local.

Safe restart accepts the whole generated stateless allowlist or one allowlisted service. Database, Redis, backup, agent, socket proxy, and other stateful services stay protected.

The single-service choices are `web`, `worker`, `celery`, `smtp-relay`, and `caddy`. `worker` runs DjangoLux's tasks on stack schema 5 (DjangoLux 1.16 with Composer 1.10); `celery` runs a project's own Celery tasks, or DjangoLux's tasks on older stacks. The panel does not see each project's `COMPOSER_AGENT_RESTART_SERVICES`, so it queues any listed service: the project's agent refuses one outside its allowlist, and the operation fails with the agent's `exit_code` and `error` (for example `Service 'worker' is not in COMPOSER_AGENT_RESTART_SERVICES.`), shown in the project's operation history.

## Batches and break glass

Batches default to concurrency one and are capped at three. Dispatch follows member order, and unstarted members are cancelled after the first failure unless continue-on-failure was selected.

Recovery deploy is superuser-only and requires `fleet.run_recovery_deploy`, the current password, an entered reason, and acknowledgement of the backup-bypass warning. It creates an immutable `BreakGlassAudit` plus the native DLUX audit entry.

## Operation visibility and stuck operations

The in-flight strip and detail modal show each operation's latest event phase, seconds since the last event, the agent's online/last-seen state, and an `overdue` flag once past `deadline_at`. An image update deliberately recreates `web`, `celery`, and `composer-agent`, so its agent is expected to go offline mid-operation (phases `awaiting_dlux`/`composer_deploy`) — the strip surfaces that as an expected restart rather than a fault.

Deadline expiry otherwise only fires when the agent next polls, so an agent lost during a recreate would leave the operation in flight forever. The `fleet.tasks.expire_stale_operations` Celery-beat task (every 120s) fails any non-terminal operation past `deadline_at` + `FLEET_OPERATION_GRACE_MINUTES` (default 10), clearing it from the strip. To unstick one immediately, cancel it from the operation history.

## Retention and rollout

Sanitized console bodies are cleared after `FLEET_OPERATION_LOG_RETENTION_DAYS` (90 by default) by daily Celery beat task `fleet.tasks.prune_operation_logs`; operation/event metadata remains. The same cleanup can be run with `python manage.py prune_fleet_operation_logs`.

Pilot staging first, then enroll this panel's own agent, a noncritical project, Decrees and Trademarks, and finally the remaining fleet. Keep each pre-agent Compose file under `.xpose` until verified. Composer `watch` remains the rollback-compatible resident mode for one migration cycle.

Agent self-update is deliberately not registered in protocol v1. Add it only after the staging/pilot deployment path is stable, using an ephemeral supervisor with canary-first rollout, reconnection verification, and automatic previous-image restoration.

Keep local DLUX authentication for the initial control-plane rollout. After fleet stability, deploy `django-lux-sso` as a separate DLUX project with its own agent, register the panel and managed applications as OIDC clients, and map provider roles into each application's native scopes/groups. OIDC never replaces Composer agent credentials.

## Releasing

Releases are tag-driven. `release-manifest.json` is the single source of truth for the project version — the running app reads it via `dlux.utils.get_project_version` (DjangoLux 1.5.3+), so there is no separate `VERSION` file to maintain. Before tagging, update `release-manifest.json` (`version`, `summary`, `highlights`, `release_url`) and add the matching `## vX.Y.Z` section to `CHANGELOG.md`. The manifest `version` must equal the tag, and `release_url` must be `https://github.com/<owner>/<repo>/releases/tag/vX.Y.Z`. Then `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`.

The push fires `.github/workflows/release.yml`: `tools/validate_project_release_manifest.py` gates tag/manifest agreement, resolves the pinned `django-lux` version from `requirements.txt`, and emits both the `DLUX_BAKED_VERSION` build arg and the base64 manifest label. The amd64 image then builds and pushes to `debeski/dlux-panel:<ver>` and `:latest`, and the GitHub Release is created from the matching CHANGELOG section. Requires repo secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.

Do **not** hand-author `baked_dlux_version` in `release-manifest.json`. The validator injects it into the published label from the `requirements.txt` pin, so the two can never disagree; an unresolvable pin fails the release. DjangoLux surfaces it as a "baked dlux" badge beside the target version in the image-update review dialog.
