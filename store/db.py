"""Accès SQLite. Pas d'ORM : requêtes explicites, dicts en entrée/sortie."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Colonnes de `offers` stockées en JSON.
_JSON_COLS = {"sources", "skills", "score_breakdown", "llm_analysis"}

# Colonnes réellement présentes dans la table (garde-fou contre les clés parasites).
_OFFER_COLS = [
    "id", "fingerprint", "title", "company", "company_norm", "category",
    "description", "url", "url_canonical", "sources", "location", "remote",
    "contract_type", "work_time", "work_time_hours", "salary_raw", "salary_min",
    "salary_max", "skills", "published_at", "discovered_at", "last_checked_at",
    "score", "score_breakdown", "llm_analysis", "priority", "status", "archived",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def _encode(offer: dict) -> dict:
    row = {}
    for col in _OFFER_COLS:
        if col not in offer:
            continue
        val = offer[col]
        if col in _JSON_COLS and val is not None and not isinstance(val, str):
            val = json.dumps(val, ensure_ascii=False)
        row[col] = val
    return row


def _decode(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for col in _JSON_COLS:
        if col in d and isinstance(d[col], str):
            try:
                d[col] = json.loads(d[col])
            except (ValueError, TypeError):
                pass
    return d


def get_offer(conn: sqlite3.Connection, offer_id: str) -> dict | None:
    cur = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,))
    return _decode(cur.fetchone())


def upsert_offer(conn: sqlite3.Connection, offer: dict) -> tuple[str, bool]:
    """Insère ou met à jour. Retourne (id, is_new)."""
    offer_id = offer.get("id") or offer["fingerprint"]
    offer = {**offer, "id": offer_id}
    offer.setdefault("fingerprint", offer_id)

    ts = now_iso()
    exists = conn.execute(
        "SELECT 1 FROM offers WHERE id = ?", (offer_id,)
    ).fetchone() is not None

    if not exists:
        offer.setdefault("discovered_at", ts)
        offer.setdefault("last_checked_at", ts)
        row = _encode(offer)
        cols = ", ".join(row)
        placeholders = ", ".join(f":{c}" for c in row)
        conn.execute(f"INSERT INTO offers ({cols}) VALUES ({placeholders})", row)
        conn.commit()
        return offer_id, True

    offer["last_checked_at"] = ts
    row = _encode(offer)
    row.pop("id", None)
    row.pop("discovered_at", None)  # jamais réécrit
    if not row:
        return offer_id, False
    assignments = ", ".join(f"{c} = :{c}" for c in row)
    row["_id"] = offer_id
    conn.execute(f"UPDATE offers SET {assignments} WHERE id = :_id", row)
    conn.commit()
    return offer_id, False


def record_run(conn: sqlite3.Connection, stats: dict) -> int:
    fields = {
        "started_at": stats.get("started_at", now_iso()),
        "finished_at": stats.get("finished_at", now_iso()),
        "sources_ok": json.dumps(stats.get("sources_ok", []), ensure_ascii=False),
        "sources_failed": json.dumps(stats.get("sources_failed", []), ensure_ascii=False),
        "n_raw": stats.get("n_raw", 0),
        "n_new": stats.get("n_new", 0),
        "n_scored": stats.get("n_scored", 0),
        "n_llm": stats.get("n_llm", 0),
        "n_priority1": stats.get("n_priority1", 0),
        "n_priority2": stats.get("n_priority2", 0),
        "notes": stats.get("notes"),
    }
    cols = ", ".join(fields)
    placeholders = ", ".join(f":{c}" for c in fields)
    cur = conn.execute(f"INSERT INTO runs ({cols}) VALUES ({placeholders})", fields)
    conn.commit()
    return cur.lastrowid


def get_state(conn: sqlite3.Connection, key: str, default=None):
    cur = conn.execute("SELECT value FROM state WHERE key = ?", (key,))
    row = cur.fetchone()
    return row["value"] if row else default


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()
