"""Filtres déterministes : exclusion dure, catégorie, contrat, remote, dispo."""
from __future__ import annotations

import re
from functools import lru_cache

CATEGORIES = ("A", "B", "C")


@lru_cache(maxsize=64)
def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


def _any(patterns, text: str) -> str | None:
    for p in patterns or []:
        if _rx(p).search(text):
            return p
    return None


def _text_of(offer: dict) -> str:
    return " ".join(str(offer.get(k, "") or "") for k in ("title", "description", "location"))


# --------------------------------------------------------------------------- #
#  Catégorie
# --------------------------------------------------------------------------- #
def detect_category(text: str, cfg: dict) -> tuple[str, float]:
    scores = {c: 0.0 for c in CATEGORIES}
    for cat, patterns in (cfg.get("category_patterns") or {}).items():
        for entry in patterns:
            pat, weight = entry[0], float(entry[1])
            if _rx(pat).search(text):
                scores[cat] += weight
    best = max(scores, key=scores.get)
    return (best, scores[best]) if scores[best] >= cfg["thresholds"]["category_min"] \
        else ("UNKNOWN", scores[best])


# --------------------------------------------------------------------------- #
#  Exclusion dure
# --------------------------------------------------------------------------- #
def is_excluded(offer: dict, cfg: dict) -> tuple[bool, str | None]:
    title = str(offer.get("title", "") or "")
    desc = str(offer.get("description", "") or "")

    hit = _any(cfg.get("exclude_title_patterns"), title)
    if hit:
        # Sauf si le titre porte AUSSI un signal de catégorie fort (ex "AI Ops").
        _, cat_score = detect_category(title, cfg)
        if cat_score < cfg["thresholds"]["category_min"]:
            return True, f"titre technique: {hit}"

    hit = _any(cfg.get("exclude_description_patterns"), desc)
    if hit:
        return True, f"exigence rédhibitoire: {hit}"
    return False, None


# --------------------------------------------------------------------------- #
#  Remote / work_time / contrat / heures
# --------------------------------------------------------------------------- #
def _detect_remote(text: str, cfg: dict) -> str:
    loc = cfg.get("locations", {})
    if _any(loc.get("hybrid_terms"), text):
        return "hybrid"
    if _any(loc.get("remote_terms"), text):
        return "remote"
    if _any(loc.get("paris_terms"), text):
        return "onsite"
    return "unknown"


_HOURS_RX = re.compile(r"(\d{1,2})\s?h(?:eures|rs|)\b(?:\s?/?\s?(?:semaine|sem|week))?", re.I)
_INTERN_RX = re.compile(r"\b(stage|stagiaire|internship|intern|alternance|alternant|apprenti\w*|work[- ]study)\b", re.I)
_FREELANCE_RX = re.compile(r"\b(freelance|free-lance|ind[ée]pendant|mission|prestation|auto[- ]?entrepreneur|contractor)\b", re.I)
_PARTTIME_RX = re.compile(r"\b(part[- ]time|temps partiel|mi[- ]temps|quelques heures|few hours per week)\b", re.I)
_FULLTIME_RX = re.compile(r"\b(full[- ]time|temps plein|35\s?h|37\s?h|39\s?h)\b", re.I)


def _detect_work_time(text: str) -> tuple[str, int | None]:
    hours = None
    m = _HOURS_RX.search(text)
    if m:
        h = int(m.group(1))
        if 3 <= h <= 45:
            hours = h
    if _INTERN_RX.search(text):
        return "internship", hours
    if _FREELANCE_RX.search(text):
        return "freelance", hours
    if _PARTTIME_RX.search(text) or (hours is not None and hours <= 30):
        return "parttime", hours
    if _FULLTIME_RX.search(text) or (hours is not None and hours >= 35):
        return "fulltime", hours
    return "unknown", hours


_CONTRACT_RX = [
    ("Stage", r"\b(stage|stagiaire|internship)\b"),
    ("Alternance", r"\b(alternance|apprentissage|work[- ]study)\b"),
    ("Freelance", r"\b(freelance|mission|ind[ée]pendant|prestation)\b"),
    ("CDD", r"\bcdd\b|fixed[- ]term"),
    ("CDI", r"\bcdi\b|permanent (contract|position)"),
]


def _detect_contract(text: str, given: str | None) -> str | None:
    if given:
        return given
    for label, pat in _CONTRACT_RX:
        if re.search(pat, text, re.I):
            return label
    return None


# --------------------------------------------------------------------------- #
#  Point d'entrée
# --------------------------------------------------------------------------- #
def classify(offer: dict, cfg: dict) -> dict:
    text = _text_of(offer)
    excluded, reason = is_excluded(offer, cfg)
    category, _ = detect_category(text, cfg)

    student = bool(_any(cfg.get("student_arrangement_patterns"), text))

    penalty_flags: list[str] = []
    for flag, patterns in (cfg.get("penalty_patterns") or {}).items():
        if _any(patterns, text):
            penalty_flags.append(flag)

    given_wt = offer.get("work_time") if offer.get("work_time") not in (None, "", "unknown") else None
    given_ct = offer.get("contract_type") or None

    wt, hours = _detect_work_time(text)
    if given_wt:
        wt = given_wt
    if offer.get("work_time_hours"):
        hours = offer["work_time_hours"]

    remote = offer.get("remote") if offer.get("remote") not in (None, "", "unknown") \
        else _detect_remote(text, cfg)

    return {
        "category": category,
        "excluded": excluded,
        "exclude_reason": reason,
        "status": "excluded" if excluded else offer.get("status", "new"),
        "remote": remote,
        "work_time": wt,
        "work_time_hours": hours,
        "contract_type": _detect_contract(text, given_ct),
        "penalty_flags": penalty_flags,
        "student_arrangement": student,
    }
