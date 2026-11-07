"""Additive storage for encrypted credentials (Stage 3.1)."""
CREDENTIALS_DDL = """
CREATE TABLE IF NOT EXISTS credentials (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    encrypted_payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_credentials_owner_provider
    ON credentials(tenant_id, user_id, provider);
"""


def apply_credentials_table(c):
    c.executescript(CREDENTIALS_DDL)
    c.commit()