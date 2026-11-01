"""Optional PostgreSQL backend (guarded)."""
from __future__ import annotations

try:
    import psycopg  # type: ignore
    AVAILABLE = True
except Exception:
    AVAILABLE = False


class PostgresDatabase:
    def __init__(self, dsn: str):
        if not AVAILABLE:
            raise RuntimeError("psycopg not installed; PostgreSQL unavailable")
        self.dsn = dsn
        # minimal: store dsn; real impl would connect
        self.conn = psycopg.connect(dsn)

    def execute(self, sql, params=()):
        with self.conn.cursor() as c:
            c.execute(sql, params)
            self.conn.commit()

    def query(self, sql, params=()):
        with self.conn.cursor() as c:
            c.execute(sql, params)
            cols = [d[0] for d in c.description] if c.description else []
            return [dict(zip(cols, row)) for row in c.fetchall()]