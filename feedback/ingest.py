"""Ingestion du feedback envoyé via une issue GitHub pré-remplie.

Titre attendu : `fb:<offer_id>:<verdict>` (verdict ∈ up|star|down|exclude|applied|obtained)
Corps facultatif : une ligne `reason: <valeur>` et/ou `note: <texte libre>`.
"""
from __future__ import annotations

import json
import logging
import re

from pipeline.preferences import recompute_weights
from store import db
from store.db import now_iso

log = logging.getLogger("veille.feedback")

_TITLE_RX = re.compile(r"fb:\s*([A-Za-z0-9_\-]+)\s*:\s*(up|star|down|exclude|applied|obtained)",
                       re.IGNORECASE)
_REASON_RX = re.compile(r"^\s*reason\s*:\s*([a-z_]+)\s*$", re.IGNORECASE | re.MULTILINE)
_NOTE_RX = re.compile(r"^\s*note\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)

_VERDICT_STATUS = {
    "up": "interesting", "star": "interesting", "down": "ignored",
    "exclude": "excluded", "applied": "applied", "obtained": "obtained",
}
_VALID_REASONS = {
    "too_sales", "too_technical", "too_time_consuming", "not_enough_ai",
    "not_enough_business", "low_pay", "location", "hours", "weak_company",
    "level_too_high", "level_too_low", "other",
}


def parse_title(title: str) -> tuple[str, str] | None:
    m = _TITLE_RX.search(title or "")
    if not m:
        return None
    return m.group(1), m.group(2).lower()


def parse_reason(body: str) -> str | None:
    m = _REASON_RX.search(body or "")
    if not m:
        return None
    r = m.group(1).lower()
    return r if r in _VALID_REASONS else "other"


def parse_note(body: str) -> str | None:
    m = _NOTE_RX.search(body or "")
    return m.group(1) if m and m.group(1).lower() not in ("", "n/a") else None


def _greylist_add(conn, company_norm: str) -> None:
    if not company_norm:
        return
    cur = json.loads(db.get_state(conn, "greylist", "[]"))
    if company_norm not in cur:
        cur.append(company_norm)
        db.set_state(conn, "greylist", json.dumps(cur, ensure_ascii=False))


def apply(conn, cfg: dict, *, offer_id: str, verdict: str,
          reason: str | None, note: str | None, author: str) -> str:
    owner = str(cfg["github"].get("owner_login", "")).lower()
    if owner and author.lower() != owner:
        return f"⛔ Feedback ignoré : auteur '{author}' non autorisé."

    offer = db.get_offer(conn, offer_id)
    if offer is None:
        return f"⚠️ Offre inconnue : {offer_id} (feedback non enregistré)."

    conn.execute(
        "INSERT INTO feedback (offer_id, verdict, reason, note, created_at) VALUES (?,?,?,?,?)",
        (offer_id, verdict, reason, note, now_iso()),
    )
    new_status = _VERDICT_STATUS[verdict]
    conn.execute("UPDATE offers SET status = ? WHERE id = ?", (new_status, offer_id))
    conn.commit()

    if verdict == "exclude":
        _greylist_add(conn, offer.get("company_norm", ""))

    weights = recompute_weights(conn, cfg)
    extra = f" · poids ré-ajustés ({', '.join(f'{k}:{v:g}' for k, v in weights.items())})" \
        if weights and weights != cfg["weights"] else ""
    return (f"✅ Feedback enregistré : {verdict} sur « {offer.get('title', offer_id)} »"
            f"{f' (raison: {reason})' if reason else ''}. Statut → {new_status}.{extra}")


def handle(conn, cfg: dict, *, title: str, body: str = "", author: str = "") -> str:
    parsed = parse_title(title)
    if not parsed:
        return (f"⚠️ Titre non reconnu : « {title} ». Format attendu : "
                f"fb:<offer_id>:<up|star|down|exclude|applied|obtained>")
    offer_id, verdict = parsed
    return apply(conn, cfg, offer_id=offer_id, verdict=verdict,
                 reason=parse_reason(body), note=parse_note(body), author=author)
