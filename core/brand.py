"""BrandService - tenant-scoped persistent brand intelligence.

Approved brand knowledge is durable and tenant-scoped (shared across authorized
users/agents), held separately from conversation memory and agent-private memory.

Key properties:
- Every approved fact is an *immutable version*; edits create a new version via
  the proposal -> approval flow. Approved values are never overwritten in place.
- Each fact version is traceable to its originating proposal (`proposal_id`) and
  to the approving user (`approved_by_user_id`), with an entry in `brand_history`.
- Nothing is auto-promoted from conversation or auto-approved. `approve`/`reject`/
  `revoke` are human (admin) actions recorded in the history.
- A tenant may hold multiple brands; the "default" brand is an explicit flag.
  Brand context assembly (grounding) is a later milestone and must never silently
  merge facts across brands.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from storage.database import Database

# Brand permission names. Phase A enforces the *admin* actions (approve/reject/
# revoke, and brand management) at the API layer via role; the manifest/policy
# integration for the `brand:read` / `brand:propose` / `brand:edit` capability
# strings is a later (Phase B/C) milestone.
PERM_READ = "brand:read"
PERM_PROPOSE = "brand:propose"
PERM_EDIT = "brand:edit"
PERM_APPROVE = "brand:approve"
PERM_REVOKE = "brand:revoke"

# Documented brand-fact categories (advisory; not an exhaustive enum so the set
# can be extended additively).
CATEGORIES = (
    "identity", "mission", "values", "positioning", "voice", "tone",
    "vocabulary", "guidelines", "audience", "products", "services",
    "objectives", "priorities", "decisions", "restrictions",
)

# Credential-like terms rejected from brand fact keys/values (safety net).
_CREDENTIAL_TERMS = (
    "password", "passwd", "api_key", "apikey", "private_key", "secret_key",
    "access_token", "refresh_token", "ssn", "credential",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _looks_like_secret(key: str, value: str) -> bool:
    blob = f"{key} {value}".lower()
    return any(term in blob for term in _CREDENTIAL_TERMS)


class BrandService:
    def __init__(self, db: Database, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    # --- helpers -------------------------------------------------------
    def _brand(self, brand_id: str) -> Dict[str, Any]:
        rows = self.db.query(
            "SELECT * FROM brands WHERE id=? AND tenant_id=?",
            (brand_id, self.tenant_id))
        if not rows:
            raise ValueError("brand not found")
        return rows[0]

    def _history(self, brand_id, action, category=None, key=None, old_value=None,
                 new_value=None, proposal_id=None, fact_id=None, user_id=None):
        self.db.execute(
            "INSERT INTO brand_history (id,tenant_id,brand_id,action,category,key,old_value,new_value,proposal_id,fact_id,user_id,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), self.tenant_id, brand_id, action, category, key,
             old_value, new_value, proposal_id, fact_id, user_id, _now()))

    def _clear_other_defaults(self, keep_id):
        self.db.execute(
            "UPDATE brands SET is_default=0, updated_at=? WHERE tenant_id=? AND id<>?",
            (_now(), self.tenant_id, keep_id))

    def _latest_version(self, brand_id, category, key) -> int:
        rows = self.db.query(
            "SELECT MAX(version) AS v FROM brand_facts WHERE tenant_id=? AND brand_id=? AND category=? AND key=?",
            (self.tenant_id, brand_id, category, key))
        v = rows[0]["v"] if rows and rows[0]["v"] is not None else 0
        return int(v)

    # --- brand management ---------------------------------------------
    def create_brand(self, name: str, user_id: Optional[str] = None,
                     is_default: bool = False) -> str:
        name = (name or "").strip()
        if not name:
            raise ValueError("brand name required")
        bid = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO brands (id,tenant_id,name,is_default,created_by_user_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (bid, self.tenant_id, name, 1 if is_default else 0, user_id, _now(), _now()))
        if is_default:
            self._clear_other_defaults(bid)
        self._history(bid, "create_brand", None, None, None, name, None, None, user_id)
        return bid

    def list_brands(self) -> List[Dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM brands WHERE tenant_id=? ORDER BY created_at ASC, id ASC",
            (self.tenant_id,))

    def get_brand(self, brand_id: str) -> Dict[str, Any]:
        return self._brand(brand_id)

    def rename_brand(self, brand_id: str, name: str, user_id: Optional[str] = None):
        name = (name or "").strip()
        if not name:
            raise ValueError("brand name required")
        old = self._brand(brand_id)
        self.db.execute(
            "UPDATE brands SET name=?, updated_at=? WHERE id=? AND tenant_id=?",
            (name, _now(), brand_id, self.tenant_id))
        self._history(brand_id, "rename_brand", None, None, old["name"], name, None, None, user_id)

    def set_default_brand(self, brand_id: str, user_id: Optional[str] = None):
        self._brand(brand_id)  # validate tenant ownership
        self._clear_other_defaults(brand_id)
        self.db.execute(
            "UPDATE brands SET is_default=1, updated_at=? WHERE id=? AND tenant_id=?",
            (_now(), brand_id, self.tenant_id))
        self._history(brand_id, "set_default", None, None, None, None, None, None, user_id)

    def get_default_brand(self) -> Optional[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM brands WHERE tenant_id=? AND is_default=1 ORDER BY created_at ASC, id ASC LIMIT 1",
            (self.tenant_id,))
        return rows[0] if rows else None

    # --- facts (immutable versions) -----------------------------------
    def list_facts(self, brand_id: str, category: Optional[str] = None) -> List[Dict[str, Any]]:
        self._brand(brand_id)
        sql = "SELECT * FROM brand_facts WHERE tenant_id=? AND brand_id=? AND status='approved'"
        params: List[Any] = [self.tenant_id, brand_id]
        if category:
            sql += " AND category=?"
            params.append(category)
        sql += " ORDER BY category ASC, key ASC, created_at ASC, id ASC"
        return self.db.query(sql, tuple(params))

    def fact_versions(self, brand_id: str, category: str, key: str) -> List[Dict[str, Any]]:
        self._brand(brand_id)
        return self.db.query(
            "SELECT * FROM brand_facts WHERE tenant_id=? AND brand_id=? AND category=? AND key=? "
            "ORDER BY version ASC, created_at ASC, id ASC",
            (self.tenant_id, brand_id, category, key))

    def all_versions(self, brand_id: str) -> List[Dict[str, Any]]:
        self._brand(brand_id)
        return self.db.query(
            "SELECT * FROM brand_facts WHERE tenant_id=? AND brand_id=? "
            "ORDER BY category ASC, key ASC, version ASC, created_at ASC, id ASC",
            (self.tenant_id, brand_id))

    # --- proposals -----------------------------------------------------
    def propose(self, brand_id: str, category: str, key: str, value: str,
                agent_id: Optional[str] = None, source: str = "manual",
                reason: Optional[str] = None, context: Optional[str] = None,
                confidence: float = 0.5, base_version: Optional[int] = None,
                user_id: Optional[str] = None) -> str:
        self._brand(brand_id)
        category = (category or "").strip()
        key = (key or "").strip()
        value = (value or "").strip()
        if not category or not key or not value:
            raise ValueError("category, key, and value are required")
        if _looks_like_secret(key, value):
            raise ValueError("credential-like content cannot be stored as brand fact")
        if base_version is not None and base_version < 1:
            raise ValueError("base_version must be >= 1")
        pid = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO brand_proposals (id,tenant_id,brand_id,agent_id,category,key,value,source,reason,context,confidence,status,base_version,created_by_user_id,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, self.tenant_id, brand_id, agent_id, category, key, value, source, reason,
             context, confidence, "proposed", base_version, user_id, _now()))
        self._history(brand_id, "propose", category, key,
                      (f"v{base_version}" if base_version is not None else None),
                      value, pid, None, user_id)
        return pid

    def list_proposals(self, brand_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        self._brand(brand_id)
        if status:
            return self.db.query(
                "SELECT * FROM brand_proposals WHERE tenant_id=? AND brand_id=? AND status=? "
                "ORDER BY created_at ASC, id ASC",
                (self.tenant_id, brand_id, status))
        return self.db.query(
            "SELECT * FROM brand_proposals WHERE tenant_id=? AND brand_id=? ORDER BY created_at ASC, id ASC",
            (self.tenant_id, brand_id))

    def get_proposal(self, proposal_id: str) -> Dict[str, Any]:
        rows = self.db.query(
            "SELECT * FROM brand_proposals WHERE id=? AND tenant_id=?",
            (proposal_id, self.tenant_id))
        if not rows:
            raise ValueError("proposal not found")
        return rows[0]

    # --- approval / rejection / revocation ----------------------------
    def approve(self, proposal_id: str, user_id: str, edited_value: Optional[str] = None) -> str:
        p = self.get_proposal(proposal_id)
        if p["status"] != "proposed":
            raise ValueError(f"proposal already {p['status']}")
        brand_id = p["brand_id"]
        category = p["category"]
        key = p["key"]
        value = edited_value if edited_value is not None else p["value"]
        if edited_value is not None and _looks_like_secret(key, value):
            raise ValueError("credential-like content cannot be stored as brand fact")

        current = self._latest_version(brand_id, category, key)
        # Stale-proposal guard: an edit must match the fact's current version.
        if p["base_version"] is not None and p["base_version"] != current:
            raise ValueError("stale proposal: fact has changed since the proposal was created")

        old_value = None
        if current > 0:
            rows = self.db.query(
                "SELECT value FROM brand_facts WHERE tenant_id=? AND brand_id=? AND category=? AND key=? AND version=?",
                (self.tenant_id, brand_id, category, key, current))
            old_value = rows[0]["value"] if rows else None
            # The active version becomes superseded (never mutated in place).
            self.db.execute(
                "UPDATE brand_facts SET status='superseded', updated_at=? "
                "WHERE tenant_id=? AND brand_id=? AND category=? AND key=? AND status='approved'",
                (_now(), self.tenant_id, brand_id, category, key))

        new_version = current + 1
        fact_id = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO brand_facts (id,tenant_id,brand_id,category,key,value,source,confidence,version,status,proposal_id,approved_by_user_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (fact_id, self.tenant_id, brand_id, category, key, value, p["source"],
             p["confidence"], new_version, "approved", proposal_id, user_id, _now(), _now()))

        status = "edited" if edited_value is not None else "approved"
        self.db.execute(
            "UPDATE brand_proposals SET status=?, decided_at=?, decided_by_user_id=? WHERE id=?",
            (status, _now(), user_id, proposal_id))

        self._history(brand_id, "approve", category, key, old_value, value,
                      proposal_id, fact_id, user_id)
        return fact_id

    def reject(self, proposal_id: str, user_id: str):
        p = self.get_proposal(proposal_id)
        if p["status"] != "proposed":
            raise ValueError(f"proposal already {p['status']}")
        self.db.execute(
            "UPDATE brand_proposals SET status='rejected', decided_at=?, decided_by_user_id=? WHERE id=?",
            (_now(), user_id, proposal_id))
        self._history(p["brand_id"], "reject", p["category"], p["key"],
                      None, None, proposal_id, None, user_id)

    def revoke(self, fact_id: str, user_id: str):
        rows = self.db.query(
            "SELECT * FROM brand_facts WHERE id=? AND tenant_id=?",
            (fact_id, self.tenant_id))
        if not rows:
            raise ValueError("fact not found")
        f = rows[0]
        if f["status"] == "revoked":
            raise ValueError("fact already revoked")
        self.db.execute(
            "UPDATE brand_facts SET status='revoked', updated_at=? WHERE id=? AND tenant_id=?",
            (_now(), fact_id, self.tenant_id))
        self._history(f["brand_id"], "revoke", f["category"], f["key"],
                      f["value"], None, None, fact_id, user_id)

    # --- history -------------------------------------------------------
    def history(self, brand_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if brand_id:
            self._brand(brand_id)
            return self.db.query(
                "SELECT * FROM brand_history WHERE tenant_id=? AND brand_id=? ORDER BY created_at ASC, id ASC",
                (self.tenant_id, brand_id))
        return self.db.query(
            "SELECT * FROM brand_history WHERE tenant_id=? ORDER BY created_at ASC, id ASC",
            (self.tenant_id,))
