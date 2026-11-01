# Recovery Procedures

## Backup creation
Copy the SQLite DB file or use encrypted_backup() with a Fernet key.

## Encryption and key handling
Keys must be generated with Fernet.generate_key() and stored outside backup location (env or keychain). Never commit keys.

## Restore
Use restore() or encrypted_restore() with the same key. Verify DB opens and tests pass.

## Key-loss consequences
Encrypted backups are unrecoverable without the key.

## Backup integrity verification
Open DB, run `PRAGMA integrity_check`, run test suite.

## Recovery limitations
File-level only; no point-in-time; single-process.

## Recommended frequency/retention
Daily backups, retain 7-30 days.

## Recovery drill
1. Create encrypted backup.
2. Delete DB.
3. Restore from backup.
4. Run tests.
EOF