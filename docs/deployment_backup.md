# Backup & Recovery — Deployment Guide (M11)

## Intended deployment

Local-first, single-user, **single-process** FastAPI + SQLite deployment. One
backend (uvicorn), one SQLite database file, optional Vite frontend, Ollama for
model inference. No multi-node scale, no managed DB service. Backups are therefore
**file-level, offline-safe** operations on a single SQLite file.

## Recommended backup strategy

| Concern | Recommendation |
|---|---|
| **Type** | Full file-level backup of the SQLite DB, **encrypted** at rest (Fernet). |
| **Frequency** | Daily automatic backup (cron / systemd timer). |
| **Retention** | Keep 14 daily backups (≈2 weeks); longer-term archive copies can be moved off-box. |
| **Storage** | Local directory on the host plus periodic off-box copy (e.g., encrypted sync). |
| **Encryption key** | Fernet key kept **separately and securely** (env/secret manager/keychain), never in Git, never next to the backup. Losing the key = unrecoverable. |
| **Verification** | Encrypted backups are verified (`integrity_check = ok`) as part of the backup run; a recovery drill should be exercised periodically. |
| **Atomicity** | Backup while the app is not mid-write; the CLI uses `copy2` which is safe for a single-process app during a quiet window. For stronger safety, stop uvicorn or back up from a copy. |

> **Why encrypted file-level?** SQLite is a single file; a full copy is simple,
atomic-enough, and cheap at this scale. Encryption-at-rest protects the DB
content on disk / in transit to off-box storage. Point-in-time recovery and a
managed DB would be overkill and add a cloud dependency the project explicitly
avoids.

## Components

- `core/backup.py` — low-level `backup`/`restore`/`encrypted_backup`/`encrypted_restore`.
- `core/backup_service.py` — managed wrapper: timestamped naming, retention
  pruning, integrity verification.
- `scripts/backup.py` — `python -m scripts.backup` CLI (backup / restore / verify / list).
- `tests/test_backup_service.py` — isolated-DB tests (never production).

## Scheduling (cron)

Add a daily encrypted backup to a cron job (owner `pat` or your service user):

```cron
# 2:05 AM daily, encrypted, retain 14
5 2 * * *  cd /path/to/personal-ai-team && PAT_BACKUP_KEY="$(cat /path/to/keys/backup.key)" /path/to/venv/bin/python -m scripts.backup backup --db /path/to/data/pat.db --dir /path/to/backups --keep 14 >> /var/log/pat-backup.log 2>&1
```

## Scheduling (systemd timer) — recommended for a service deployment

`/etc/systemd/system/pat-backup.service`:
```ini
[Unit]
Description=Personal AI Team daily encrypted backup
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/personal-ai-team
EnvironmentFile=/etc/pat-backup.env   # contains PAT_BACKUP_KEY=...
ExecStart=/path/to/venv/bin/python -m scripts.backup backup --db /path/to/data/pat.db --dir /path/to/backups --keep 14
```

`/etc/systemd/system/pat-backup.timer`:
```ini
[Unit]
Description=Run Personal AI Team backup daily

[Timer]
OnCalendar=*-*-* 02:05:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemctl enable --now pat-backup.timer
systemctl list-timers pat-backup.timer
```

## Operations

```bash
# Backup (encrypted)
PAT_BACKUP_KEY=... python -m scripts.backup backup --db .../data/pat.db --dir /path/to/backups

# Verify a backup
PAT_BACKUP_KEY=... python -m scripts.backup verify --file /path/to/backups/pat-pat.db-<TS>.enc

# Restore to an explicit target (never to the live DB path unless truly desired)
PAT_BACKUP_KEY=... python -m scripts.backup restore --file /path/to/backups/pat-pat.db-<TS>.enc --db /path/to/restored.db

# List backups
python -m scripts.backup list --dir /path/to/backups
```

## Restore runbook

1. Stop the backend (so it is not writing to the DB).
2. Restore to a **fresh** path: `... restore --file <backup.enc> --db <restored.db>`.
3. Verify: open the restored DB, run `PRAGMA integrity_check` (the CLI's
   `verify` does this).
4. Confirm key records are present.
5. Swap the live DB path to the restored file (or replace the live file from a
   quiet state) and restart the backend.
6. Run the test suite against an isolated DB to confirm the app boots.

## Key-loss consequence

Encrypted backups are unrecoverable without the Fernet key. Keep the key in a
secret manager / keychain / owner-only file, separate from the backups. Never
commit it to Git and never write it into documentation.
