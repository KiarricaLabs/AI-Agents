"""Backup and restore utilities."""
from __future__ import annotations

import shutil
from pathlib import Path
from storage.database import Database


def backup(db_path: str, dest: str):
    shutil.copy2(db_path, dest)
    return dest


def restore(backup_path: str, db_path: str):
    shutil.copy2(backup_path, db_path)
    return db_path


def encrypted_backup(db_path: str, dest: str, key: bytes):
    from core.tracing import start_span, end_span
    span = start_span("backup.encrypted", {})
    from cryptography.fernet import Fernet
    f = Fernet(key)
    data = Path(db_path).read_bytes()
    Path(dest).write_bytes(f.encrypt(data))
    end_span(span)
    return dest


def encrypted_restore(backup_path: str, db_path: str, key: bytes):
    from cryptography.fernet import Fernet
    f = Fernet(key)
    data = f.decrypt(Path(backup_path).read_bytes())
    Path(db_path).write_bytes(data)
    return db_path