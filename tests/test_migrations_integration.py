"""T2-C-7 Phase 1C — migration idempotency and persistence checks.

Verifies the additive T2-C migrations wired into ``storage/database.py``:

- A ``Database`` construction fully initializes the schema (base schema + all
  additive T2-C tables).
- Initializing the SAME database file again (a second ``Database`` construction)
  is idempotent: it succeeds, does not duplicate or partially create schema, and
  leaves existing T2-C rows and table structure intact.

This exercises the real migration wiring (``Database.__init__``), not a bespoke
script, and does not modify any production migration code.
"""
from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone

from storage.database import Database

# Every additive table created by the T2-C migrations (t2c1/t2c3/t2c4/t2c5).
T2C_TABLES = [
    "team_goals",
    "team_goal_steps",
    "team_goal_approvals",
    "coordination_plans",
    "coordination_plan_steps",
    "coordination_executions",
    "coordination_step_outputs",
    "coordination_deliverables",
    "coordination_deliverable_versions",
    "coordination_deliverable_approvals",
]


def _fresh_path() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(db, table):
    return [dict(r) for r in db.query(f"PRAGMA table_info({table})")]


def _table_names(db):
    return {dict(r)["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _value_for(table, col, typ):
    if col == "id":
        return f"{table}-{uuid.uuid4().hex[:12]}"
    if typ and "INT" in typ.upper():
        return 1
    if "permissions" in col:
        return "[]"
    if "json" in col:
        return "{}"
    if col.endswith("_at"):
        return _now()
    return "val"


def _schema_snapshot(db):
    """name/type pairs per T2-C table, used to compare structure before/after."""
    return {t: [(c["name"], c["type"]) for c in _columns(db, t)] for t in T2C_TABLES}


class MigrationPersistenceTest(unittest.TestCase):
    def test_t2c_migrations_idempotent_and_non_destructive(self):
        path = _fresh_path()
        db = Database(path=path, tenant_id="m1")

        # 1. every T2-C table exists after initialization
        names = _table_names(db)
        for t in T2C_TABLES:
            self.assertIn(t, names, f"{t} missing after init")

        # 2. exactly one copy of each T2-C table (no duplicate schema)
        for t in T2C_TABLES:
            n = db.query(
                "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name=?",
                (t,))[0]["n"]
            self.assertEqual(n, 1, f"{t} is duplicated")

        before = _schema_snapshot(db)

        # 3. insert a representative row into every T2-C table (all columns)
        marker = {}
        for t in T2C_TABLES:
            cols = _columns(db, t)
            col_names = [c["name"] for c in cols]
            types = {c["name"]: c["type"] for c in cols}
            vals = [_value_for(t, n, types[n]) for n in col_names]
            placeholders = ",".join("?" for _ in col_names)
            db.execute(
                f"INSERT INTO {t} ({','.join(col_names)}) VALUES ({placeholders})",
                vals)
            marker[t] = vals[0]  # the id (first column)
        for t in T2C_TABLES:
            self.assertEqual(db.query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"], 1, t)

        # 4. re-initialize the SAME database file (full additive schema again)
        db2 = Database(path=path, tenant_id="m1")

        # 5. schema intact & identical after re-initialization
        self.assertEqual(_schema_snapshot(db2), before)
        for t in T2C_TABLES:
            n = db2.query(
                "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name=?",
                (t,))[0]["n"]
            self.assertEqual(n, 1, f"{t} duplicated after re-init")

        # 6. existing rows intact, no duplication, exact rows survive
        for t in T2C_TABLES:
            self.assertEqual(db2.query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"], 1, t)
            self.assertEqual(
                db2.query(f"SELECT COUNT(*) AS n FROM {t} WHERE id=?", (marker[t],))[0]["n"],
                1, t)

    def test_each_t2c_table_has_ownership_and_key_columns(self):
        """Sanity-check that representative identity/ownership columns exist."""
        path = _fresh_path()
        db = Database(path=path, tenant_id="m2")
        required = {
            "team_goals": ["tenant_id", "user_id", "status"],
            "team_goal_steps": ["tenant_id", "user_id", "team_goal_id", "seq"],
            "team_goal_approvals": ["tenant_id", "user_id", "team_goal_id", "decision"],
            "coordination_plans": ["tenant_id", "user_id", "team_goal_id", "status"],
            "coordination_plan_steps": ["tenant_id", "user_id", "plan_id", "seq",
                                        "effective_permissions"],
            "coordination_executions": ["tenant_id", "user_id", "plan_id", "status"],
            "coordination_step_outputs": ["tenant_id", "user_id", "execution_id",
                                          "seq", "status"],
            "coordination_deliverables": ["tenant_id", "user_id", "execution_id",
                                          "status"],
            "coordination_deliverable_versions": ["tenant_id", "user_id",
                                                  "deliverable_id", "version", "status"],
            "coordination_deliverable_approvals": ["tenant_id", "user_id",
                                                   "version_id", "decision"],
        }
        for t, cols in required.items():
            present = {c["name"] for c in _columns(db, t)}
            missing = [c for c in cols if c not in present]
            self.assertEqual(missing, [], f"{t} missing columns {missing}")


if __name__ == "__main__":
    unittest.main()
