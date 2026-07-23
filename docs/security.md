# Security

- Agent traffic is outbound-only public HTTPS. The agent exposes no listener.
- The raw Docker socket is mounted only into `docker-socket-proxy`; the agent uses its restricted API network.
- Generated agents have `no-new-privileges`, all capabilities dropped, a read-only identical-path project mount, and read/write access only to DLUX runtime and private agent state.
- Agent IDs are public identifiers; enrollment tokens and bearer secrets are random credentials. The database stores password hashes only.
- DLUX scopes, groups, and permissions filter both fleet UI and direct human API access. Machine API authorization is bound to exactly one `ManagedProject`.
- Shared snapshots/results contain typed display and operation fields, never environment dumps, application secrets, agent bearer values, backup artifacts, or unrestricted logs.
- Shell, `run`, build, down, purge, database restart, and remote backup restore are rejected by Composer and the control plane.
- Future OIDC changes human authentication only. Composer machine credentials never become OIDC sessions or clients.
