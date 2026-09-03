"""Orchestrateur : collecte -> dédup -> filtres -> score -> LLM -> archivage."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from pipeline import preferences, score
from pipeline.dedup import canonical_url, fingerprint, find_duplicate, merge_sources, normalize_company
from pipeline.filter_rules import classify
from pipeline.llm_analyze import analyze, reset_circuit, should_analyze
from settings import env
from sources import SOURCES
from store import db
from store.db import now_iso

log = logging.getLogger("veille.run")

_RESCORE_STATUSES = ("new", "seen", "interesting")
_ACTIVE_STATUSES = ("new", "seen", "interesting", "applied", "obtained")


def _with_greylist(conn, cfg: dict) -> dict:
    grey = json.loads(db.get_state(conn, "greylist", "[]"))
    if not grey:
        return cfg
    hp = dict(cfg.get("hard_preferences") or {})
    hp["exclude_companies"] = list(hp.get("exclude_companies", [])) + grey
    return {**cfg, "hard_preferences": hp}


def _to_offer(raw: dict) -> dict:
    company = raw.get("company", "") or ""
    title = raw.get("title", "") or ""
    loc = raw.get("location", "") or ""
    fp = fingerprint(company, title, loc)
    cu = canonical_url(raw.get("url", ""))
    src = raw.get("source", "")
    return {
        "id": fp,
        "fingerprint": fp,
        "title": title,
        "company": company,
        "company_norm": normalize_company(company),
        "description": raw.get("description", "") or "",
        "url": raw.get("url", ""),
        "url_canonical": cu,
        "sources": [{"source": src, "url": raw.get("url", ""),
                     "external_id": raw.get("external_id", ""), "seen_at": now_iso()}],
        "location": loc,
        "remote": raw.get("remote") or "unknown",
        "contract_type": raw.get("contract_type"),
        "work_time": raw.get("work_time") or "unknown",
        "salary_raw": raw.get("salary_raw"),
        "published_at": raw.get("published_at"),
        "status": "new",
    }


def _collect(cfg: dict, names) -> tuple[list[dict], list[str], list[str]]:
    raw: list[dict] = []
    ok: list[str] = []
    failed: list[str] = []
    for name, fn in SOURCES.items():
        if names and name not in names:
            continue
        try:
            offers = fn(cfg) or []
            raw.extend(o.as_dict() if hasattr(o, "as_dict") else o for o in offers)
            ok.append(name)
        except Exception as e:  # noqa: BLE001 — une source ne doit jamais tuer le scan
            log.exception("source %s a échoué", name)
            failed.append(f"{name}: {type(e).__name__}")
    return raw, ok, failed


def _upsert_with_dedup(conn, raw: dict) -> tuple[str, bool]:
    cand = _to_offer(raw)
    dup_id = find_duplicate(conn, cand)
    if dup_id:
        existing = db.get_offer(conn, dup_id)
        merged = merge_sources(existing, cand)
        db.upsert_offer(conn, merged)
        return dup_id, False
    return db.upsert_offer(conn, cand)


def _score_offer(conn, cfg, offer: dict, weights: dict, penalties: dict,
                 api_key: str | None, allow_llm: bool,
                 llm_budget: list[int] | None = None) -> tuple[dict, bool]:
    fields = classify(offer, cfg)
    offer = {**offer, **fields}
    pre, _ = score.prescore(offer, cfg)
    offer["pre_score"] = pre

    used_llm = False
    llm = offer.get("llm_analysis")
    budget_ok = llm_budget is None or llm_budget[0] > 0
    if allow_llm and budget_ok and not fields["excluded"] and should_analyze(offer, cfg):
        models = cfg["thresholds"]["llm"].get("models")
        result = analyze(offer, api_key, tuple(models) if models else None)
        if result is not None:
            llm = result
            used_llm = True
            if llm_budget is not None:
                llm_budget[0] -= 1

    final = score.final_score(offer, cfg, weights, llm, penalties)
    update = {
        "id": offer["id"],
        "category": fields["category"],
        "remote": fields["remote"],
        "work_time": fields["work_time"],
        "work_time_hours": fields["work_time_hours"],
        "contract_type": fields["contract_type"],
        "status": fields["status"],
        "score": final["score"],
        "priority": final["priority"],
        "score_breakdown": final["score_breakdown"],
        "llm_analysis": llm,
        "last_checked_at": now_iso(),
    }
    db.upsert_offer(conn, update)
    return update, used_llm


def _archive_old(conn, cfg) -> int:
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=cfg["cleanup"]["max_age_days"])).isoformat()
    cur = conn.execute(
        "UPDATE offers SET archived = 1 "
        "WHERE archived = 0 AND status IN ('new','seen') AND discovered_at < ?",
        (cutoff,),
    )
    conn.commit()
    return cur.rowcount


def scan(conn, cfg: dict, *, source_names=None) -> dict:
    started = now_iso()
    reset_circuit()
    cfg = _with_greylist(conn, cfg)
    raw, ok, failed = _collect(cfg, source_names)

    new_ids: list[str] = []
    for r in raw:
        if not (r.get("title") and r.get("url")):
            continue
        oid, is_new = _upsert_with_dedup(conn, r)
        if is_new:
            new_ids.append(oid)

    weights = preferences.current_weights(conn, cfg)
    penalties = preferences.feedback_penalties(conn, cfg)
    api_key = env("GEMINI_API_KEY")

    n_llm = 0
    n_p1 = n_p2 = 0
    new_p1: list[str] = []
    rows = conn.execute(
        "SELECT id FROM offers WHERE archived = 0 AND status IN "
        f"({','.join('?' * len(_RESCORE_STATUSES))})", _RESCORE_STATUSES
    ).fetchall()

    # Ordre de traitement : meilleur pré-score d'abord, pour que le budget LLM
    # aille aux offres les plus prometteuses si les nouvelles offres sont nombreuses.
    scored_pre = []
    for row in rows:
        offer = db.get_offer(conn, row["id"])
        offer = {**offer, **classify(offer, cfg)}
        pre, _ = score.prescore(offer, cfg)
        scored_pre.append((pre, row["id"]))
    scored_pre.sort(reverse=True)

    llm_budget = [cfg["thresholds"]["llm"].get("max_per_run", 60)]
    for _pre, oid in scored_pre:
        offer = db.get_offer(conn, oid)
        update, used_llm = _score_offer(conn, cfg, offer, weights, penalties,
                                        api_key, allow_llm=True, llm_budget=llm_budget)
        n_llm += int(used_llm)
        if update["priority"] == 1:
            n_p1 += 1
            if oid in new_ids:
                new_p1.append(oid)
        elif update["priority"] == 2:
            n_p2 += 1

    weights = preferences.recompute_weights(conn, cfg) or weights
    n_archived = _archive_old(conn, cfg)

    stats = {
        "started_at": started, "finished_at": now_iso(),
        "sources_ok": ok, "sources_failed": failed,
        "n_raw": len(raw), "n_new": len(new_ids), "n_scored": len(rows),
        "n_llm": n_llm, "n_priority1": n_p1, "n_priority2": n_p2,
        "notes": f"archivées: {n_archived}",
    }
    db.record_run(conn, stats)
    stats["new_priority1_ids"] = new_p1
    log.info("scan terminé: %s", stats)
    return stats


def recompute(conn, cfg: dict) -> dict:
    """Re-score toutes les offres actives sans re-collecter (ex: après changement de config)."""
    cfg = _with_greylist(conn, cfg)
    weights = preferences.current_weights(conn, cfg)
    penalties = preferences.feedback_penalties(conn, cfg)
    rows = conn.execute(
        "SELECT id FROM offers WHERE archived = 0 AND status IN "
        f"({','.join('?' * len(_ACTIVE_STATUSES))})", _ACTIVE_STATUSES
    ).fetchall()
    for row in rows:
        offer = db.get_offer(conn, row["id"])
        _score_offer(conn, cfg, offer, weights, penalties, None, allow_llm=False)
    return {"rescored": len(rows)}
