# Security Readiness

- JWT HMAC tokens with tenant/user/role claims; local mode trusted identity.
- Refresh token rotation, reuse detection, revocation.
- Rate limiting (in-memory, single-process).
- Policy engine default-deny; enforced in task/delegation/orchestrator.
- Admin-only tenant-scoped audit export.
- Encrypted backups (Fernet); keys never stored with backups.
- No plaintext credential fallback.
- Tenant isolation enforced at DB query level.
- No secrets in logs/metrics/traces.
- Limitations: single-process rate limiter; no WAF/KMS in local dev.
EOF