# DLUX Control Plane

Dedicated DjangoLux project for monitoring and safely operating a fleet of DLUX Compose deployments through one outbound `composer-agent` per project.

## Boundaries

- DLUX projects remain authoritative for backup, maintenance, monitoring, update locks, permissions, and application state.
- Composer agents own Docker execution, registry checks, durable relay, redaction, and reconnection.
- This panel owns scoped fleet presentation, enrollment, command routing, batches, audit history, and the latest relayed snapshot.
- Human login and future OIDC are independent from agent bearer credentials.

The machine API is `/api/agent/v1/` and the production Compose web service runs `config.asgi:application` with Uvicorn. It accepts only typed image update, backup creation, safe restart, audited recovery deployment, and credential-rotation messages. There is no arbitrary shell, build, down, purge, database restart, backup restore, or agent listener.

## Local setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py dlux_setup --skip-configure
```

Sign in as a superuser, complete `/sys/setup/`, add managed projects under `/fleet/`, and create a one-use enrollment token from each project page. Set the target project's `COMPOSER_CONTROL_URL` to this panel's public HTTPS URL and `COMPOSER_ENROLLMENT_TOKEN` to the displayed token. The token expires after 15 minutes and is never shown again.

The panel's generated `compose.yml` includes its own `composer-agent`. Enroll it only after initial administrative setup so the panel can later update itself and replay the result after its UI returns.

## Verification

```bash
DEBUG_STATUS=False PYTHONPATH=../pkg-django-lux ../pkg-django-lux/.venv/bin/python manage.py test fleet.tests --settings=config.test_settings
python -m compileall -q fleet config
docker compose config
```

See [Agent Protocol v1](docs/agent-protocol-v1.md) and [Operations](docs/operations.md).
