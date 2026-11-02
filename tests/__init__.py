"""Test-suite bootstrap: force all backend tests onto an isolated database.

Import order matters. Running the suite as ``python -m unittest discover -s
tests -t . -v`` (or ``python -m unittest tests.test_something``) imports this
package *before* any test module, so ``PAT_DB_PATH`` is set before
``config.settings`` (and therefore ``api.app`` and the routers) resolve the
``DB_PATH`` constant at import time.

By default the suite runs against a brand-new temporary SQLite database that is
deleted on process exit, so no test records can accumulate in the real
application database. A developer can point the suite at a specific isolated
directory by setting ``PAT_TEST_DB_DIR``.

This module fails fast (rather than silently writing) if the resolved test
database would ever be the real application database at ``data/pat.db``.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

# The one real database we must never touch during tests.
_REAL_DB = (Path(__file__).resolve().parent.parent / "data" / "pat.db").resolve()

# Exported so tooling/reporting can identify the active test DB.
_TEST_DB_PATH: str | None = None


def _resolve_test_db() -> str:
    global _TEST_DB_PATH

    override_dir = os.environ.get("PAT_TEST_DB_DIR")
    if override_dir:
        test_dir = Path(override_dir).resolve()
        test_dir.mkdir(parents=True, exist_ok=True)
        owns_dir = False
    else:
        test_dir = Path(tempfile.mkdtemp(prefix="pat-tests-"))
        owns_dir = True

    db_path = (test_dir / "test.db").resolve()

    if db_path == _REAL_DB:
        raise RuntimeError(
            "Refusing to run tests: the resolved test database equals the real "
            f"application database ({_REAL_DB}). Set PAT_TEST_DB_DIR to an "
            "isolated directory instead."
        )

    # Never let the test database accidentally resolve to the real one.
    os.environ["PAT_DB_PATH"] = str(db_path)
    _TEST_DB_PATH = str(db_path)

    if owns_dir:
        atexit.register(lambda: shutil.rmtree(test_dir, ignore_errors=True))

    return str(db_path)


_resolve_test_db()
