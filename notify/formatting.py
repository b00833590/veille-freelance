"""Mise en forme commune digest / dashboard : carte d'offre lisible."""
from __future__ import annotations

from urllib.parse import quote

_COMPONENT_LABELS = {
    "missions_fit": "Missions alignées",
    "student_compat": "Compatible avec les études",
    "ai_business": "IA appliquée + business",
    "non_technical": "Accessible sans profil technique",
    "location": "Localisation / remote",
    "cv_potential": "Bon pour le CV",
}
_REMOTE_LABELS = {"remote": "Remote", "hybrid": "Hybride", "onsite": "Sur site",
                  "unknown": "Lieu à préciser"}
_WT_LABELS = {"freelance": "Freelance", "parttime": "Temps partiel",
              "internship": "Stage", "fulltime": "Temps plein", "unknown": "Format à préciser"}


def issue_url(cfg: dict, offer_id: str, verdict: str) -> str:
    gh = cfg["github"]
    body = quote("reason: \nnote: ")
    return (f"https://github.com/{gh['owner']}/{gh['repo']}/issues/new"
            f"?labels=feedback&title=fb:{offer_id}:{verdict}&body={body}")


def _top_reasons(breakdown: dict, n: int = 4) -> list[str]:
    comps = [(k, v) for k, v in breakdown.items()
             if not k.startswith("_") and isinstance(v, dict)]
    comps.sort(key=lambda kv: kv[1].get("points", 0), reverse=True)
    out = []
    for name, v in comps[:n]:
        if v.get("points", 0) <= 0:
            continue
        out.append(f"{_COMPONENT_LABELS.get(name, name)} — {v.get('reason', '')}")
    return out


def attention_points(offer: dict) -> list[str]:
    pts: list[str] = []
    llm = offer.get("llm_analysis")
    if isinstance(llm, dict):
        pts.extend(llm.get("red_flags", []) or [])
    bd = offer.get("score_breakdown") or {}
    hp = bd.get("_hard_preferences")
    if isinstance(hp, dict) and hp.get("reason"):
        pts.append(hp["reason"])
    if "full_time" in (offer.get("penalty_flags") or []) and not offer.get("student_arrangement"):
        pts.append("Annoncé temps plein — vérifier la possibilité d'aménagement étudiant")
    return pts[:4]


def offer_card(offer: dict, cfg: dict, *, match_notes: list[str] | None = None) -> dict:
    bd = offer.get("score_breakdown") or {}
    salary = offer.get("salary_raw") or "Rémunération non précisée"
    return {
        "id": offer["id"],
        "title": offer.get("title", ""),
        "company": offer.get("company") or "Entreprise non précisée",
        "score": offer.get("score", 0),
        "priority": offer.get("priority", 3),
        "category": offer.get("category", "UNKNOWN"),
        "location": offer.get("location") or "—",
        "remote": _REMOTE_LABELS.get(offer.get("remote", "unknown"), offer.get("remote", "")),
        "work_time": _WT_LABELS.get(offer.get("work_time", "unknown"), offer.get("work_time", "")),
        "salary": salary,
        "url": offer.get("url", ""),
        "published_at": offer.get("published_at") or "",
        "why": _top_reasons(bd),
        "match_notes": match_notes or [],
        "attention": attention_points(offer),
        "description": (offer.get("description") or "")[:400],
        "feedback": {v: issue_url(cfg, offer["id"], v)
                     for v in ("up", "star", "down", "exclude", "applied")},
    }
