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