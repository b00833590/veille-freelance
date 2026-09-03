"""Génère docs/data.json + docs/index.html (dashboard statique, GitHub Pages)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from notify.formatting import offer_card
from pipeline.preferences import explain_match
from store import db
from store.db import now_iso

log = logging.getLogger("veille.report")
_TEMPLATE = Path(__file__).with_name("template.html")

_POS = ("up", "star", "applied", "obtained")
_NEG = ("down", "exclude")


def _offers_payload(conn, cfg) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM offers WHERE archived = 0 ORDER BY score DESC"
    ).fetchall()
    out = []
    for r in rows:
        o = db.get_offer(conn, r["id"])
        card = offer_card(o, cfg, match_notes=explain_match(conn, o))
        card.update({
            "status": o.get("status", "new"),
            "sources": [s.get("source") for s in (o.get("sources") or []) if isinstance(s, dict)],
            "score_breakdown": o.get("score_breakdown") or {},
            "discovered_at": o.get("discovered_at", ""),
            "is_paris": "paris" in (o.get("location") or "").lower()
                        or "île-de-france" in (o.get("location") or "").lower(),
        })
        out.append(card)
    return out


def _stats(conn) -> dict:
    (analysed,) = conn.execute("SELECT COUNT(*) FROM offers").fetchone()
    (retained,) = conn.execute(
        "SELECT COUNT(*) FROM offers WHERE priority IN (1,2) AND archived = 0"
    ).fetchone()
    (n_feedback,) = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()
    (applications,) = conn.execute(
        "SELECT COUNT(DISTINCT offer_id) FROM feedback WHERE verdict IN ('applied','obtained')"
    ).fetchone()

    cat_liked, cat_disliked = {}, {}
    for row in conn.execute("""
        SELECT o.category c, f.verdict v FROM feedback f JOIN offers o ON o.id = f.offer_id
    """):
        bucket = cat_liked if row["v"] in _POS else (cat_disliked if row["v"] in _NEG else None)
        if bucket is not None:
            bucket[row["c"]] = bucket.get(row["c"], 0) + 1

    liked_companies = [r["company"] for r in conn.execute("""
        SELECT o.company, COUNT(*) n FROM feedback f JOIN offers o ON o.id = f.offer_id
        WHERE f.verdict IN ('up','star','applied','obtained') AND o.company != ''
        GROUP BY o.company_norm ORDER BY n DESC LIMIT 8
    """)]

    reasons = {r["reason"]: r["n"] for r in conn.execute(
        "SELECT reason, COUNT(*) n FROM feedback WHERE reason IS NOT NULL GROUP BY reason ORDER BY n DESC"
    )}

    weights_history = [
        {"at": r["snapshot_at"], "weights": json.loads(r["weights"]),
         "n": r["feedback_count"], "confidence": r["confidence"]}
        for r in conn.execute("SELECT * FROM pref_weights ORDER BY id ASC")
    ]

    last_run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()

    return {
        "analysed": analysed,
        "retained": retained,
        "feedback_count": n_feedback,
        "feedback_rate": round(n_feedback / analysed, 3) if analysed else 0,
        "applications": applications,
        "categories_liked": cat_liked,
        "categories_disliked": cat_disliked,
        "liked_companies": liked_companies,
        "reject_reasons": reasons,
        "weights_history": weights_history,
        "last_run": dict(last_run) if last_run else None,
    }


def build(conn, cfg: dict, out_dir: str = "docs") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": now_iso(),
        "github": cfg["github"],
        "thresholds": cfg["thresholds"],
        "offers": _offers_payload(conn, cfg),
        "stats": _stats(conn),
    }
    (out / "data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    (out / "index.html").write_text(_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    log.info("dashboard: %d offres -> %s", len(payload["offers"]), out)
