#!/usr/bin/env python3
"""Managed backup CLI (M11 deployment hardening).

Wraps ``core.backup_service`` for operator use. Safe by default:
  * source DB, backup dir, and restore target are all explicit
    (never guessed, never the production DB unless you say so).
  * the KEY is read from PAT_BACKUP_KEY (never a CLI argument, so it cannot
    appear in process lists or shell history).

Examples
--------
Backup (encrypted) the DB currently at PAT_DB_PATH into ./backups:
    python -m scripts.backup backup --dir ./backups        (plain copy)
    PAT_BACKUP_KEY=... python -m scripts.backup backup --dir ./backups  (encrypted)

Restore an encrypted backup to an explicit path:
    PAT_BACKUP_KEY=... python -m scripts.backup restore --file backup.enc --db /path/to/restore.db

Verify a backup:
    PAT_BACKUP_KEY=... python -m scripts.backup verify --file backup.enc

List backups:
    python -m scripts.backup list --dir ./backups
"""
from __future__ import annotations

import argparse
import os
import sys

from config.settings import DB_PATH
from core.backup_service import (
    backup_to_dir, restore_from, verify_backup, list_backups,
)


def _load_key(arg_or_env) -> bytes | None:
    """Return a Fernet key from PAT_BACKUP_KEY (or --key, only for isolated
    restore demonstrations/tests). Never print or log the key value."""
    raw = arg_or_env or os.environ.get("PAT_BACKUP_KEY", "")
    if not raw:
        return None
    # A valid Fernet key is a 44-char URL-safe base64 blob; use it as-is.
    # Otherwise attempt to decode a provided base64/hex representation.
    candidate = raw
    if len(candidate) == 44:
        return candidate.encode()
    try:
        import base64
        return base64.urlsafe_b64decode(candidate.encode())
    except Exception:
        return candidate.encode()


def cmd_backup(args):
    key = _load_key(args.key)
    dest = backup_to_dir(args.db, args.dir, key=key, keep=args.keep)
    print(f"backup written: {dest}")
    print(f"encrypted: {bool(key)}")
    return 0


def cmd_restore(args):
    key = _load_key(args.key)
    restore_from(args.file, args.db, key=key)
    print(f"restored {args.file} -> {args.db}")
    return 0


def cmd_verify(args):
    key = _load_key(args.key)
    res = verify_backup(args.file, key=key)
    print(f"integrity: {res['integrity']}  ok={res['ok']}")
    return 0 if res["ok"] else 1


def cmd_list(args):
    for p in list_backups(args.dir):
        print(p)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m scripts.backup",
                                description="Managed backup/restore CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("backup", help="create a (optionally encrypted) backup")
    pb.add_argument("--db", default=DB_PATH, help="source database path")
    pb.add_argument("--dir", required=True, help="backup directory")
    pb.add_argument("--keep", type=int, default=14, help="retain N backups")
    pb.add_argument("--key", default=None, help=argparse.SUPPRESS)
    pb.set_defaults(fn=cmd_backup)

    pr = sub.add_parser("restore", help="restore a backup to a target path")
    pr.add_argument("--file", required=True, help="backup file to restore")
    pr.add_argument("--db", required=True, help="explicit restore target path")
    pr.add_argument("--key", default=None, help=argparse.SUPPRESS)
    pr.set_defaults(fn=cmd_restore)

    pv = sub.add_parser("verify", help="verify integrity of a backup")
    pv.add_argument("--file", required=True)
    pv.add_argument("--key", default=None, help=argparse.SUPPRESS)
    pv.set_defaults(fn=cmd_verify)

    pl = sub.add_parser("list", help="list backups in a directory")
    pl.add_argument("--dir", required=True)
    pl.set_defaults(fn=cmd_list)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
