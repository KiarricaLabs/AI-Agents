# Preservation Status — M6 (Project Frozen)

## Milestone state

- **M6 commit:** `ed8a5bcf5d2524bfb4c5055070ee9a2942c515d0`
- **Tag:** `m6-complete` (annotated) → `ed8a5bcf5d2524bfb4c5055070ee9a2942c515d0`
- **M0–M7:** closed
- **M6:** preserved (artifacts below)
- **M8:** NOT authorized

## Backup artifacts

| Artifact | Location |
|---|---|
| Portable Git bundle | `/Users/kiarricafavors/personal-ai-team-backups/m6-complete-20261101-072642/personal-ai-team.git.bundle` |
| Source archive | `/Users/kiarricafavors/personal-ai-team-backups/m6-complete-20261101-072642/personal-ai-team-source.tar.gz` |
| Encrypted database backup | `/Users/kiarricafavors/personal-ai-team-backups/m6-complete-20261101-072642/database/pat.db.enc` |
| Fernet key (kept separate) | `/Users/kiarricafavors/personal-ai-team-backups/keys/m6-complete-20261101-072642.key` |
| Authoritative recovery guide | `RECOVERY.md` in the backup directory (`/Users/kiarricafavors/personal-ai-team-backups/m6-complete-20261101-072642/RECOVERY.md`) |

## Verification

- **Portable Git bundle:** `git bundle verify` → ok, complete history. A clean-room clone restored `main` and the `m6-complete` tag; commit `ed8a5bcf5d2524bfb4c5055070ee9a2942c515d0` was present (`cat-file -t` = `commit`).
- **Encrypted database:** decrypted with the separately stored key → `PRAGMA integrity_check` = `ok`, `quick_check` = `ok`, row counts matched the live database. A wrong key was rejected (`InvalidToken`), confirming genuine encryption with no plaintext fallback.

## Fernet key handling (critical)

The Fernet key **must be preserved separately and securely** (owner-only permissions; never committed to Git; never written into documentation). The key value is intentionally **not** recorded here or in `RECOVERY.md`. Losing the key makes `pat.db.enc` unrecoverable — there is no plaintext fallback.

## Deployment blocker

`core/auth.py` contains `SECRET = "change-me-in-prod"`. **Production deployment is blocked** until this is replaced with a securely configured production secret, and any tokens previously signed with the placeholder are rotated/invalidated.

## Boundaries

- The original Social Media Manager (`/Users/kiarricafavors/AI Agent`) was not touched.
- No application code, database contents, credentials, keys, Git history, tags, or backup artifacts were modified during this documentation closeout.
