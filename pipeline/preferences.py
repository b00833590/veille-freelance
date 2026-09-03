"""Apprentissage V1 : ajustement lent et borné des poids de scoring + explications.

Principe : les poids sont recalculés DEPUIS les défauts (`config.yaml > weights`) à
chaque fois, jamais en dérive cumulative. Le feedback ne fait que déplacer chaque
poids de ±2 (10-40 feedbacks) ou ±5 (>40). Les préférences explicites du fichier de
config priment toujours (appliquées ailleurs, dans score.py).
"""
from __future__ import annotations

import json

from pipeline.score import COMPONENTS
from store.db import now_iso

_POS = {"up", "star", "applied", "obtained"}
_NEG = {"down", "exclude"}


def current_weights(conn, cfg: dict) -> dict:
    row = conn.execute(
        "SELECT weights FROM pref_weights ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row:
        try:
            return json.loads(row["weights"])
        except (ValueError, TypeError):
            pass
    return dict(cfg["weights"])


def _feedback_rows(conn):
    return conn.execute("""
        SELECT f.verdict, o.score_breakdown
        FROM feedback f JOIN offers o ON o.id = f.offer_id
    """).fetchall()


def recompute_weights(conn, cfg: dict) -> dict | None:
    rows = _feedback_rows(conn)
    n = len(rows)
    defaults = dict(cfg["weights"])

    if n < 10:
        _maybe_write(conn, defaults, n, "low")
        return defaults

    cap, confidence = (2.0, "med") if n <= 40 else (5.0, "high")

    # Corrélation signe(verdict) x (fraction de la composante - 0.5).
    acc = {c: [] for c in COMPONENTS}
    for r in rows:
        sign = 1 if r["verdict"] in _POS else (-1 if r["verdict"] in _NEG else 0)
        if sign == 0:
            continue
        try:
            bd = json.loads(r["score_breakdown"])
        except (ValueError, TypeError):
            continue
        for c in COMPONENTS:
            comp = bd.get(c)
            if comp and comp.get("max"):
                frac = comp["points"] / comp["max"]
                acc[c].append(sign * (frac - 0.5) * 2)

    weights = {}
    for c in COMPONENTS:
        corr = sum(acc[c]) / len(acc[c]) if acc[c] else 0.0
        delta = max(-cap, min(cap, corr * cap))
        weights[c] = max(1.0, defaults[c] + delta)

    total = sum(weights.values())
    weights = {c: round(w * 100 / total, 2) for c, w in weights.items()}

    _maybe_write(conn, weights, n, confidence)
    return weights


def _maybe_write(conn, weights: dict, n: int, confidence: str) -> None:
    last = conn.execute(
        "SELECT weights FROM pref_weights ORDER BY id DESC LIMIT 1"
    ).fetchone()
    rounded = {k: round(v, 1) for k, v in weights.items()}
    if last:
        try:
            prev = {k: round(v, 1) for k, v in json.loads(last["weights"]).items()}
            if prev == rounded:
                return
        except (ValueError, TypeError):
            pass
    conn.execute(
        "INSERT INTO pref_weights (snapshot_at, weights, feedback_count, confidence, trigger) "
        "VALUES (?, ?, ?, ?, 'auto')",
        (now_iso(), json.dumps(weights, ensure_ascii=False), n, confidence),
    )
    conn.commit()


def feedback_penalties(conn, cfg: dict) -> dict:
    """Pénalités douces par composante, dérivées des raisons de rejet récurrentes."""
    mapping = cfg.get("reason_signal_map") or {}
    counts = {}
    for r in conn.execute(
        "SELECT reason, COUNT(*) n FROM feedback WHERE reason IS NOT NULL GROUP BY reason"
    ):
        counts[r["reason"]] = r["n"]

    penalties: dict[str, float] = {}
    for reason, rule in mapping.items():
        if counts.get(reason, 0) >= rule.get("min_count", 3):
            comp = rule["component"]
            penalties[comp] = penalties.get(comp, 0.0) + float(rule.get("penalty", 5))
    return penalties


def explain_match(conn, offer: dict) -> list[str]:
    liked = conn.execute("""
        SELECT o.company_norm, o.category, o.remote, o.work_time
        FROM feedback f JOIN offers o ON o.id = f.offer_id
        WHERE f.verdict IN ('up','star','applied','obtained')
    """).fetchall()
    if not liked:
        return []

    phrases: list[str] = []
    cn = offer.get("company_norm", "")
    if cn and any(row["company_norm"] == cn for row in liked):
        phrases.append(f"Tu as déjà apprécié une offre de « {offer.get('company', cn)} »")
    same_cat = sum(1 for row in liked if row["category"] == offer.get("category"))
    if same_cat >= 2 and offer.get("category") in ("A", "B", "C"):
        phrases.append(f"{same_cat} offres appréciées dans la même catégorie ({offer['category']})")
    if offer.get("remote") in ("remote", "hybrid"):
        same_remote = sum(1 for row in liked if row["remote"] == offer["remote"])
        if same_remote >= 2:
            phrases.append(f"Tu privilégies les offres « {offer['remote']} » ({same_remote} appréciées)")
    if offer.get("work_time") in ("parttime", "freelance", "internship"):
        same_wt = sum(1 for row in liked if row["work_time"] == offer["work_time"])
        if same_wt >= 2:
            phrases.append(f"Format « {offer['work_time']} » déjà retenu {same_wt} fois")
    return phrases
