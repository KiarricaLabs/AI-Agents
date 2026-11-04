"""Managed backup & recovery service (M11 deployment hardening).

Wraps the low-level ``core.backup`` helpers with the operational behaviour a
local-first single-process deployment needs: timestamped, encrypted backups in a
managed directory, retention/pruning, integrity verification, and safe restore
to an explicit target path. Nothing here ever touches the production database on
its own — the source DB, backup directory, and restore target are always caller
supplied and never guessed.

Use the CLI (``python -m scripts.backup``) or call these functions directly for
scheduling (cron/systemd). Scheduled backup is intentionally an *external*
process trigger (cron / systemd timer) rather than a background worker inside the
application process: this matches the local-first single-process architecture and
keeps the app free of autonomous background activity.
"""
from __future__ import annotations

import os
from pathlib import Path

from core.backup import backup, restore, encrypted_backup, encrypted_restore
from core.tracing import start_span, end_span


def _spansafe(fn, *a, **k):
    span = start_span(fn.__name__, {})
    try:
        return fn(*a, **k)
    finally:
        end_span(span)


def backup_to_dir(db_path: str, backup_dir: str, key: bytes | None = None,
                  keep: int = 14, prefix: str = "pat") -> str:
    """Create a timestamped (optionally encrypted) backup and prune old ones.

    Returns the path written. ``keep`` controls pruning: only the ``keep`` most
    recent backups (by mtime) matching the prefix are retained. Set ``keep`` to 0
    to disable pruning. Encrypted when ``key`` is provided; otherwise a plain
    copy (usable for a disposable dev DB and for the restore demonstration).
    """
    db_path = str(db_path)
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    stamp = Path(db_path).name + "-" + _timestamp()
    dest = Path(backup_dir) / (f"{prefix}-{stamp}.enc" if key else f"{prefix}-{stamp}.db")

    if key:
        _spansafe(encrypted_backup, db_path, str(dest), key)
    else:
        _spansafe(backup, db_path, str(dest))

    if keep and keep > 0:
        _prune(Path(backup_dir), prefix, keep)
    return str(dest)


def restore_from(backup_path: str, db_path: str, key: bytes | None = None) -> str:
    """Restore a backup (plain or encrypted) to an explicit target path.

    The target directory is created if needed. ``db_path`` must be an explicit
    path — the caller decides where recovery goes; this never writes to a
    default/guessed location.
    """
    db_path = str(db_path)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    if key:
        _spansafe(encrypted_restore, str(backup_path), db_path, key)
    else:
        _spansafe(restore, str(backup_path), db_path)
    return db_path


def verify_backup(backup_path: str, key: bytes | None = None) -> dict:
    """Decrypt/verify a backup by restoring it to a temp file and running
    SQLite integrity_check. Returns a result dict; never raises on a valid file."""
    import tempfile

    tmpdir = tempfile.mkdtemp(prefix="pat-restore-check-")
    target = os.path.join(tmpdir, "verify.db")
    try:
        restore_from(backup_path, target, key)
        integrity = _integrity_check(target)
        return {"ok": integrity == "ok", "integrity": integrity, "restored_to": target}
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def list_backups(backup_dir: str, prefix: str = "pat") -> list:
    d = Path(backup_dir)
    if not d.is_dir():
        return []
    return sorted(
        [p for p in d.iterdir() if p.is_file() and p.name.startswith(prefix + "-")],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )


def _prune(backup_dir: Path, prefix: str, keep: int):
    items = list_backups(str(backup_dir), prefix)
    for old in items[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def _integrity_check(path: str) -> str:
    import sqlite3
    con = sqlite3.connect(path)
    try:
        row = con.execute("PRAGMA integrity_check;").fetchone()
        return str(row[0]) if row else "unknown"
    finally:
        con.close()


def _timestamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
