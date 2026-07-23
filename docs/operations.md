# Operations

## Enrollment and availability

Create a `ManagedProject` in its native DLUX scope, then create an enrollment token from its project page. Tokens are single-use and expire after 15 minutes. Store the control URL and token in the target deployment's private environment and recreate `composer-agent`. The resulting random bearer secret persists in that project's dedicated agent-state volume; the panel stores only its hash.

Credential rotation is issued as a typed command. The server stages a pending hash, the agent persists the new secret in SQLite, confirms with it, and only then promotes it and revokes the old credential. Interrupted confirmations replay from durable state. Revocation blocks central traffic immediately without disabling local DLUX updates.

## Updates, backups, and restart

A normal central update chooses data, full, or skipped backup and enters the same DLUX queue/lock as a local request. Terminal central success waits for DLUX finalization after Composer recreate and health checks. Backup rejection/failure prevents the Composer trigger.

Central backup creation supports data or full backups. The project-local DLUX backup engine owns artifacts and publishes approved status/history through snapshots. Restore stays local.

Safe restart accepts the whole generated stateless allowlist or one allowlisted service. Database, Redis, backup, agent, socket proxy, and other stateful services stay protected.

## Batches and break glass

Batches default to concurrency one and are capped at three. Dispatch follows member order, and unstarted members are cancelled after the first failure unless continue-on-failure was selected.

Recovery deploy is superuser-only and requires `fleet.run_recovery_deploy`, the current password, an entered reason, and acknowledgement of the backup-bypass warning. It creates an immutable `BreakGlassAudit` plus the native DLUX audit entry.

## Retention and rollout

Sanitized console bodies are cleared after `FLEET_OPERATION_LOG_RETENTION_DAYS` (90 by default) by daily Celery beat task `fleet.tasks.prune_operation_logs`; operation/event metadata remains. The same cleanup can be run with `python manage.py prune_fleet_operation_logs`.

Pilot staging first, then enroll this panel's own agent, a noncritical project, Decrees and Trademarks, and finally the remaining fleet. Keep each pre-agent Compose file under `.xpose` until verified. Composer `watch` remains the rollback-compatible resident mode for one migration cycle.

Agent self-update is deliberately not registered in protocol v1. Add it only after the staging/pilot deployment path is stable, using an ephemeral supervisor with canary-first rollout, reconnection verification, and automatic previous-image restoration.

Keep local DLUX authentication for the initial control-plane rollout. After fleet stability, deploy `django-lux-sso` as a separate DLUX project with its own agent, register the panel and managed applications as OIDC clients, and map provider roles into each application's native scopes/groups. OIDC never replaces Composer agent credentials.

## Releasing

Releases are tag-driven. Before tagging, bump `VERSION`, add the `## vX.Y.Z` section to `CHANGELOG.md`, and update `release-manifest.json` (its `version` must equal `VERSION` and the tag, and `release_url` must be `https://github.com/DEVGREIDC/dlux-panel/releases/tag/vX.Y.Z`). Then `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`.

The push fires `.github/workflows/release.yml`: `tools/validate_project_release_manifest.py` gates tag/`VERSION`/manifest agreement, then the amd64 image builds and pushes to `debeski/dlux-panel:<ver>` and `:latest` (baking the DjangoLux version and base64 release manifest into image labels), and the GitHub Release is created from the matching CHANGELOG section. Requires repo secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`.
