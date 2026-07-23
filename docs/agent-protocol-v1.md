# Agent Protocol v1

The versioned API is rooted at `/api/agent/v1/`. JSON documents are schema version 1 and capped at 65,536 encoded bytes.

## Endpoints

| Method and path | Purpose |
| --- | --- |
| `POST enroll/` | Consume a 15-minute one-use token and return agent ID plus random bearer secret. |
| `GET commands/next/?wait=25` | Long-poll for one typed command. |
| `POST operations/<uuid>/events/` | Accept monotonic acceptance, phase, and terminal events. |
| `PUT snapshot/` | Replace the project's current approved DLUX snapshot. |
| `POST local-operations/` | Reconcile a local DLUX update result after reconnect. |
| `PUT capabilities/` | Report agent/protocol versions and action capabilities. |
| `POST credentials/rotate/` | Stage and return a pending random credential. |
| `POST credentials/rotate/confirm/` | Confirm the persisted pending credential and revoke the old hash. |

Every authenticated request sends `X-Composer-Agent-ID` and `Authorization: Bearer ...`. Only password hashes are stored. Explicit revocation is immediate. A project is displayed offline 90 seconds after last contact, but connectivity loss never creates a deployment result.

States are `queued → delivered → accepted → running → succeeded|failed`. Queued or delivered commands may be cancelled; an agent must receive acknowledgement of its accepted event before execution, closing the delivered-cancellation race. Event sequences start at one, increase without gaps, acknowledge exact replay, and reject conflicts.

Actions are `dlux.image_update`, `dlux.backup.create`, `composer.restart`, `composer.recovery_deploy`, and internal `agent.rotate_credentials`. Payload fields are action-specific and unknown fields fail closed. Backup restore and arbitrary execution are not registered.

The Composer repository owns the canonical detailed contract and fixtures. Identical examples are kept in `fleet/tests/fixtures/agent-protocol-v1/` and the DjangoLux bridge suite.
