#!/usr/bin/env python3
"""Seed brand + approved memory context (M11 Fix 2).

Purpose: the brand system and approved-memory tables exist but are empty, so no
thread ever carried "On Us" brand context or persistent facts — the founder had to
reintroduce the brand every conversation. This seeds/updates an approved default
brand with brand facts, plus a small set of approved profile memories, into an
*explicit* isolated database.

CORRECTED (2026-11-04): On Us is a Black-centered, community-first social
platform for the Bay Area. This seed replaces the earlier generic brand facts.

UPDATE SEMANTICS
---------------
- Brand facts are immutable versioned rows. If a fact's latest approved value
  differs from the desired value, the seed proposes a new version on the current
  base_version and approves it (superseding the old value). Idempotent: re-running
  with the same desired values produces no new proposals.

SAFETY
------
- The database path is ALWAYS an explicit --db argument (or PAT_DB_PATH if set).
  It never touches the default data/pat.db and never guesses a path.
- Only inserts approved, non-sensitive facts.

Usage
-----
    PAT_DB_PATH=~/pat-manual-test.db python -m scripts.seed_brand_context
    # or
    python -m scripts.seed_brand_context --db ~/pat-manual-test.db
"""
from __future__ import annotations

import argparse
import os
import sys

from storage.database import Database
from core.brand import BrandService
from core.memory import MemoryService

# "On Us" — a Black-centered, community-first social platform (Bay Area).
ON_US_BRAND = "On Us"
ON_US_FACTS = [
    # (category, key, value)
    ("identity", "brand_name", "On Us"),
    ("positioning", "positioning", "A Black-centered, community-first social platform — not another app competing for attention."),
    ("positioning", "black_exclusive", "Black-centered, but not Black-exclusive."),
    ("mission", "mission", "Give the Black community a place to connect, discover resources, support businesses, and build meaningful relationships — without making everything about followers, algorithms, or going viral."),
    ("products", "platform", "A social platform for culture, conversations, local businesses, creators, and opportunities in one digital space."),
    ("products", "features", "The Feed (community social feed for posts, photos, videos, experiences); The Porch (conversation space around daily prompts, neighborhood discussions, and recommendations); Verts (short-form vertical video for creators and community); Discovery & Marketplace (find Black-owned businesses and local products/services); Groups & Events (organize around shared interests and communities)."),
    ("audience", "primary_audience", "Black community members, creators, entrepreneurs, and local businesses in Oakland and the surrounding San Francisco Bay Area."),
    ("audience", "geographic_focus", "Oakland and the surrounding San Francisco Bay Area."),
    ("voice", "voice", "Warm, direct, grounded, and community-first — helps without overclaiming; never hypes followers or virality."),
    ("voice", "tone", "Professional and approachable; clear and friendly when talking to the user, polished in drafted documents."),
    ("values", "values", "Cultural belonging, tangible opportunity, and community power — supporting one another and building collectively."),
    ("values", "brand_message", "Our culture. Our people. Our space."),
    ("values", "campaign_theme", "The Porch — Where we connect."),
    ("monetization", "business_plans", "Business plans advertised on the website, ranging from $19-$99/month."),
    ("stage", "current_stage", "Early access — building the initial community through a public Bay Area waitlist. The immediate priority is growing a meaningful local user base."),
    ("objectives", "primary_business_priority", "Grow the Oakland and Bay Area waitlist and convert early interest into active community members."),
]

# Approved profile memories for the local user (founder).
USER_ID = "local"
PROFILE_MEMORY = [
    # (kind, key, value, agent_id)
    ("profile", "user_identity", "Founder of On Us, a Black-centered community-first social platform starting in Oakland and the Bay Area.", "executive_assistant"),
    ("profile", "preferred_tone", "Direct, warm, and practical; flag tradeoffs and next steps.", "strategist"),
]


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m scripts.seed_brand_context")
    p.add_argument("--db", default=os.environ.get("PAT_DB_PATH", ""),
                   help="explicit isolated database path (REQUIRED)")
    p.add_argument("--tenant", default="local")
    p.add_argument("--confirm", action="store_true",
                   help="acknowledge you are seeding an isolated test DB")
    args = p.parse_args(argv)

    db_path = (args.db or "").strip()
    if not db_path:
        print("ERROR: --db path is required (or set PAT_DB_PATH). Never seed the default.")
        return 2
    if not args.confirm:
        print("WARNING: this seeds data. Re-run with --confirm to proceed on: " + db_path)
        return 1

    db = Database(path=db_path, tenant_id=args.tenant)
    bs = BrandService(db=db, tenant_id=args.tenant)
    ms = MemoryService(db=db, tenant_id=args.tenant)

    # --- Brand ---
    brands = bs.list_brands()
    brand = next((b for b in brands if b["name"] == ON_US_BRAND), None)
    if brand is None:
        bid = bs.create_brand(ON_US_BRAND, user_id=USER_ID, is_default=True)
        print(f"created default brand '{ON_US_BRAND}' ({bid})")
    else:
        bid = brand["id"]
        print(f"brand '{ON_US_BRAND}' already exists ({bid}); leaving in place")
        if not any(b.get("is_default") for b in bs.list_brands()):
            bs.set_default_brand(bid, user_id=USER_ID)
            print("  -> set as default")

    # For each desired fact, compare against the current approved value and
    # propose+approve a new version only if it differs (idempotent).
    facts = bs.list_facts(bid)
    current_by_key = {(f["category"], f["key"]): f["value"] for f in facts}
    added = 0
    for category, key, value in ON_US_FACTS:
        cur = current_by_key.get((category, key))
        if cur == value:
            continue
        base_version = None
        # find the latest version of an existing fact so the stale-guard passes
        if (category, key) in current_by_key:
            versions = bs.fact_versions(bid, category, key) or []
            if versions:
                base_version = versions[-1]["version"]  # latest
        pid = bs.propose(bid, category, key, value, source="seed",
                         agent_id="system", base_version=base_version, user_id=USER_ID)
        bs.approve(pid, USER_ID)
        added += 1
        print(f"  {'updated' if base_version else 'added'} fact: {category}/{key}")
    print(f"brand facts changed: {added} (matching ones kept)")

    # --- Approved profile memory (idempotent by key) ---
    existing_mem = {m["key"] for m in ms.list_profile(USER_ID)}
    mem_added = 0
    for kind, key, value, agent_id in PROFILE_MEMORY:
        if key in existing_mem:
            continue
        pid = ms.propose(USER_ID, agent_id, kind, key, value, source="seed", confidence=0.95)
        ms.approve(pid, USER_ID)
        mem_added += 1
    print(f"profile memories added: {mem_added} (existing kept)")

    print(f"done. brand facts now: {len(bs.list_facts(bid))}; profile items now: {len(ms.list_profile(USER_ID))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
