# Known Limitations

- PostgreSQL support is experimental (no real migration/rollback test).
- Rate limiter is in-memory, single-process.
- Metrics are in-memory (not Prometheus client).
- Tracing is manual hooks (no OTLP exporter).
- Memory analytics are aggregate counts only.
- Backup is file-level (no point-in-time recovery).
- Frontend is scaffold; M6 outstanding items remain.
- No external integrations or desktop automation (by design).
EOF