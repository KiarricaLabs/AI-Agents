# Deployment Security (M11 Phase 4)

## 1. Intended deployment environment

Local-first, single-user, single-process deployment:

- One FastAPI backend (uvicorn) on a private host/VM or a single developer workstation.
- One SQLite database file.
- Optional Vite frontend (static build served or dev server).
- Ollama for local model inference (no cloud model dependency).
- No Kubernetes, no multi-node scale, no managed database service.

This document specifies security requirements **for exposing this app beyond
trusted localhost**, i.e. `PAT_LOCAL_MODE=0` (require JWT).

## 2. Authentication (non-local)

**Enable fail-closed auth by starting with `PAT_LOCAL_MODE=0`.**

| Setting | Value |
|---|---|
| `PAT_LOCAL_MODE` | `0` (require server-verified JWT on every protected path) |
| `PAT_AUTH_SECRET` | strong random secret (≥32 bytes) |
| Access tokens | JWT-HMAC (SHA-256), 1-hour TTL, `sub`/`tenant`/`role`/`exp`/`jti` claims |
| Refresh tokens | server-stored hash, 7-day TTL, per-family rotation, reuse detection revokes the whole family |

### How it works (verified in code)
- `api/app.py` security middleware: paths outside `/health`, `/metrics` require a
  valid `x-token` JWT; missing/invalid → `401`.
- `core/auth.verify_token` validates signature (constant-time compare), checks
  `exp`, returns claims or `None`.
- `core/auth.issue_token` signs with `resolve_signing_secret()` (fail-closed).
- `PAT_LOCAL_MODE=0` + unset `PAT_AUTH_SECRET` → **refuses to start**
  (`core.auth.validate_auth_secret`).
- `startup guard`: `api.app` calls `validate_auth_secret()` at import; an
  insecure/placeholder secret aborts startup.

### Configuring the secret
```bash
# Generate a strong secret (never commit, never put on the CLI/history)
python -c "import secrets; print(secrets.token_hex(32))"
# Provide via environment (secret manager / systemd EnvironmentFile / keychain)
export PAT_AUTH_SECRET=<generated>
export PAT_LOCAL_MODE=0
```

## 3. Secret handling & rotation

### Handling
- `PAT_AUTH_SECRET` — signing secret; kept in a secret manager / env /
  `EnvironmentFile` (0600), **never in Git**, never in CLI args.
- `PAT_MASTER_KEY` — Fernet key for encrypted credentials/backups; stored
  separately from any encrypted data, owner-only permissions.
- `PAT_BACKUP_KEY` — Fernet key for encrypted backups (see `docs/deployment_backup.md`).
- No plaintext credential fallback, no secrets in logs/metrics/traces (verified
  in `core/auth`, `core/tracing`, `core/metrics`).

### Rotation procedure
1. Generate a new `PAT_AUTH_SECRET`.
2. Restart the backend with the new secret.
3. All previously issued JWTs become invalid (signature no longer matches) —
   clients re-authenticate.
4. Rotate `PAT_MASTER_KEY` / `PAT_BACKUP_KEY` by re-encrypting backups/credentials
   with the new key; keep the old key long enough to decrypt in-flight backups.
5. Revoke outstanding refresh tokens via `revoke_refresh` (or family) as needed.

## 4. Rate limiting (actual enforcement)

- `core.ratelimit.RateLimiter` is **in-memory per process**, keyed by client IP.
- Wired in `api/app.py` middleware; returns `429` when the limit is exceeded.
- **Current default in app.py is `RateLimiter(max_calls=100000, window=60)`** —
  effectively **no limit** for a single-user local deployment. This is a
  deliberate permissive default that should be tightened when exposing the app.
- **Limitation:** single-process in-memory only — not shared across multiple
  backend processes and resets on restart.

**Recommended production value for a hosted single-user deployment:**
```python
_rl = RateLimiter(max_calls=120, window=60)   # ~2 req/s sustained
```
For anything internet-facing, place a reverse proxy (nginx) or load balancer in
front and enforce rate limits there (stateless, scales, survives restarts).

## 5. Deployment-specific security requirements (checklist)

- [ ] `PAT_LOCAL_MODE=0` and a strong `PAT_AUTH_SECRET` generated and stored in a secret manager.
- [ ] Reverse proxy (nginx/Caddy) terminates TLS; backend bound to `127.0.0.1` only, never exposed directly.
- [ ] `PAT_AUTH_SECRET`, `PAT_MASTER_KEY`, `PAT_BACKUP_KEY` not in Git, not in CLI history, not in the frontend bundle.
- [ ] Rate limiting enforced at the proxy **and** tightened in-app from the permissive default.
- [ ] Backups automated (see `docs/deployment_backup.md`) and encrypted.
- [ ] Backend listening on a private interface; firewall restricts ports to the proxy only.
- [ ] Review CORS: `app.add_middleware(CORSMiddleware, allow_origins=["*"])` is permissive; restrict to the actual frontend origin in production.
- [ ] No production credentials or DB accessed during development/testing.

### Notable current posture (verified)
- JWT HMAC with 1h TTL + rotating refresh tokens with reuse detection: **sound**.
- Fail-closed non-local auth: **sound**.
- Rate limiting: **wired but permissive default (100k/60s)** — tighten for external exposure.
- CORS is **allow-all** — tighten in production.
- No TLS at the app layer — rely on a reverse proxy.
