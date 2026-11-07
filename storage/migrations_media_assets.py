"""Additive storage for generated media assets (Phase E2)."""
MEDIA_ASSETS_DDL = """
CREATE TABLE IF NOT EXISTS media_assets (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    project_id TEXT,
    prompt TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def apply_media_assets_table(c):
    c.executescript(MEDIA_ASSETS_DDL)
    c.commit()