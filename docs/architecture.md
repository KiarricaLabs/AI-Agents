# Architecture

Local-first, multi-tenant-capable personal AI team platform.

- core/: LLM client, memory, tasks, delegation, episodes, orchestrator, auth, policy, metrics, tracing, backup, jobs, analytics.
- storage/: SQLite (default) + optional guarded Postgres.
- agents/: manifest-driven registry (tutor, soundboard, communications, executive_assistant, workspace_architect, strategist).
- api/: FastAPI routers.
- frontend/: Vite/React scaffold.

All state persisted in SQLite; Postgres optional. No mandatory Redis.
EOF