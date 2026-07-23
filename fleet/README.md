# Fleet

This app is the scoped DLUX control plane for outbound Composer agents.

## Responsibilities

- `ManagedProject` is assigned through native DLUX scopes.
- `ComposerAgent` stores only credential hashes and connection metadata.
- `FleetOperation`/`OperationEvent` implement schema-v1 command and event durability.
- `ProjectSnapshot` stores only the latest approved DLUX relay document.
- `FleetBatch` gates dispatch at concurrency one by default and three maximum.

## Boundaries

- Agent traffic is outbound HTTPS only; the project exposes no agent listener.
- Supported remote actions are image update, allowlisted restart, audited recovery deploy, and credential rotation.
- Arbitrary shell, build, down, purge, database restart, and remote restore are never accepted.
- Human authentication and future OIDC remain independent from agent credentials.
