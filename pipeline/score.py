"""Scoring explicable 0-100 : 6 composantes pondérées + ajustement LLM borné."""
from __future__ import annotations

import re
from functools import lru_cache

from pipeline.filter_rules import detect_category

COMPONENTS = ("missions_fit", "student_compat", "ai_business", "non_technical",
              "location", "cv_potential")

_LLM_ADJ_CAP = 15
_TECH_LIGHT_TERMS = [
    r"\bsql\b", r"\bpython\b", r"\bjavascript\b", r"\bapi\b", r"\bgit\b",
    r"data pipeline", r"machine learning model", r"technical background",
    r"bases? de données", r"programmation",
]
_COLDCALL_TERMS = [r"cold call", r"phoning", r"prospection t[ée]l[ée]phonique",
                   r"appels sortants", r"outbound calls"]


@lru_cache(maxsize=128)
def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


def _count(patterns, text: str) -> int:
    return sum(1 for p in patterns if _rx(p).search(text))


def _text(offer: dict) -> str:
    return " ".join(str(offer.get(k, "") or "")
                    for k in ("title", "description", "location", "company"))


def _blend(det: float, llm_val, present: bool) -> float:
    if not present or llm_val is None:
        return det
    return 0.5 * det + 0.5 * (float(llm_val) / 100.0)


# --------------------------------------------------------------------------- #
def _components(offer: dict, cfg: dict, llm: dict | None) -> dict[str, dict]:
    text = _text(offer)
    has_llm = bool(llm)
    out: dict[str, dict] = {}

    # 1. Adéquation missions -------------------------------------------------
    cat = offer.get("category") or detect_category(text, cfg)[0]
    title_cat, title_score = detect_category(str(offer.get("title", "") or ""), cfg)
    strong_title = title_cat in ("A", "B", "C") and title_score >= cfg["thresholds"]["category_min"]
    if cat in cfg.get("category_patterns", {}):
        pats = cfg["category_patterns"][cat]
        matched = sum(1 for e in pats if _rx(e[0]).search(text))
        frac = 0.3 + 0.7 * (matched / max(1, len(pats)))
        # Titre = intitulé cible quasi exact -> plancher élevé, même sans description.
        if strong_title and title_cat == cat:
            frac = max(frac, 0.72)
    else:
        frac = 0.12  # catégorie inconnue : très peu d'adéquation présumée
    frac = _blend(min(frac, 1.0), (llm or {}).get("profile_fit"), has_llm)
    out["missions_fit"] = {"_frac": frac,
                           "reason": f"catégorie {cat}, correspondance missions"}

    # 2. Compatibilité étudiant ------------------------------------------
    wt = offer.get("work_time", "unknown")
    student = offer.get("student_arrangement", False)
    flags = offer.get("penalty_flags", [])
    if wt in ("freelance", "parttime", "internship"):
        frac = 0.95
    elif wt == "fulltime":
        frac = 0.55 if student else 0.15
    else:
        frac = 0.55  # format non précisé : incertitude, pas un signal négatif
    if "full_time" in flags and not student:
        frac = min(frac, 0.2)
    hours = offer.get("work_time_hours")
    if hours:
        frac = min(frac, 1.0) if hours <= 25 else (0.6 if hours <= 32 else 0.2)
    reason = f"temps de travail: {wt}" + (" (aménagement étudiant)" if student else "")
    frac = _blend(frac, (llm or {}).get("schedule_compatibility"), has_llm)
    out["student_compat"] = {"_frac": frac, "reason": reason}

    # 3. Intérêt IA / business --------------------------------------------
    n_ai = _count(cfg.get("ai_terms", []), text)
    n_biz = _count(cfg.get("business_terms", []), text)
    frac = min(1.0, n_ai * 0.16 + n_biz * 0.11)
    # Les catégories A (AI ops) et C (formation IA) sont intrinsèquement IA :
    # plancher même quand la description manque (offre LinkedIn sans détail).
    if strong_title and title_cat in ("A", "C"):
        frac = max(frac, 0.42)
    elif strong_title and title_cat == "B":
        frac = max(frac, 0.3)
    frac = _blend(frac, (llm or {}).get("ai_business_interest"), has_llm)
    out["ai_business"] = {"_frac": frac,
                          "reason": f"{n_ai} termes IA, {n_biz} termes business"}

    # 4. Accessibilité sans profil technique -----------------------------
    tech_hits = _count(_TECH_LIGHT_TERMS, text)
    frac = max(0.0, 1.0 - 0.2 * tech_hits)
    lvl = (llm or {}).get("technical_level_required")
    if has_llm and lvl:
        frac = 0.5 * frac + 0.5 * {"none": 1.0, "light": 0.8,
                                   "moderate": 0.4, "heavy": 0.1}.get(lvl, 0.5)
    out["non_technical"] = {"_frac": frac,
                            "reason": f"{tech_hits} signaux techniques" +
                                      (f", niveau LLM={lvl}" if has_llm and lvl else "")}

    # 5. Localisation / remote ------------------------------------------
    remote = offer.get("remote", "unknown")
    is_paris = bool(_rx("|".join(cfg["locations"]["paris_terms"])).search(text))
    frac = {"remote": 1.0, "hybrid": 0.9}.get(remote)
    if frac is None:
        frac = 0.85 if is_paris else (0.5 if remote == "unknown" else 0.3)
    out["location"] = {"_frac": frac,
                       "reason": f"{remote}" + (" · Paris/IdF" if is_paris else "")}

    # 6. Potentiel CV / intérêt pro -----------------------------------
    bonus = _count(cfg.get("company_bonus_terms", []), text)
    frac = min(1.0, 0.5 + 0.25 * bonus)
    frac = _blend(frac, (llm or {}).get("professional_interest"), has_llm)
    out["cv_potential"] = {"_frac": frac,
                           "reason": f"{bonus} signaux entreprise (startup/fintech/conseil)"}

    return out


def _weighted(components: dict, weights: dict) -> tuple[int, dict]:
    breakdown = {}
    total = 0.0
    for name in COMPONENTS:
        w = float(weights.get(name, 0))
        pts = round(components[name]["_frac"] * w, 1)
        total += pts
        breakdown[name] = {"points": pts, "max": w, "reason": components[name]["reason"]}
    return round(total), breakdown


# --------------------------------------------------------------------------- #
def prescore(offer: dict, cfg: dict) -> tuple[int, dict]:
    """Score déterministe seul, poids par défaut. Sert de pré-filtre LLM."""
    return _weighted(_components(offer, cfg, None), cfg["weights"])


def priority_of(score: int, cfg: dict) -> int:
    t = cfg["thresholds"]
    if score >= t["priority1"]:
        return 1
    if score >= t["priority2"]:
        return 2
    return 3


def _apply_hard_preferences(offer: dict, cfg: dict, score: int,
                            components: dict) -> tuple[int, list[str]]:
    hp = cfg.get("hard_preferences") or {}
    notes: list[str] = []
    text = _text(offer)

    cap_ft = hp.get("cap_if_full_time")
    if cap_ft and offer.get("work_time") == "fulltime" and not offer.get("student_arrangement"):
        if score > cap_ft:
            notes.append(f"plafonné à {cap_ft} (temps plein sans aménagement)")
            score = cap_ft

    if hp.get("no_cold_calling") and _count(_COLDCALL_TERMS, text) >= 2:
        if score > 40:
            notes.append("plafonné à 40 (préférence: pas de cold calling)")
            score = 40

    mar = hp.get("min_ai_ratio")
    if mar and components["ai_business"]["_frac"] < float(mar) and score > 55:
        notes.append(f"plafonné à 55 (part IA < {mar})")
        score = 55

    cn = offer.get("company_norm", "")
    if cn and cn in {c.lower() for c in hp.get("exclude_companies", [])}:
        notes.append("entreprise en liste grise")
        return 0, notes

    for pat in hp.get("exclude_if", []):
        if _rx(pat).search(text):
            notes.append(f"exclu par préférence: {pat}")
            return 0, notes

    return score, notes


_GATE_SENIOR_CAP = 45
_GATE_GEO_CAP = 38


_GATE_NOISE_CAP = 40


def _relevance_gate(offer: dict, cfg: dict, comps: dict, score: int) -> tuple[int, list[str]]:
    """Plafonds toujours actifs (indépendants des préférences utilisateur)."""
    notes: list[str] = []
    if "too_senior" in (offer.get("penalty_flags") or []) and score > _GATE_SENIOR_CAP:
        notes.append(f"plafonné à {_GATE_SENIOR_CAP} (poste sénior / non junior)")
        score = _GATE_SENIOR_CAP
    if offer.get("geo_ok") is False and score > _GATE_GEO_CAP:
        notes.append(f"plafonné à {_GATE_GEO_CAP} (hors Paris / France / remote Europe)")
        score = _GATE_GEO_CAP
    # Ni dans une catégorie cible, ni de composante IA/business : c'est du bruit.
    if (offer.get("category", "UNKNOWN") == "UNKNOWN"
            and comps["ai_business"]["_frac"] < 0.2 and score > _GATE_NOISE_CAP):
        notes.append(f"plafonné à {_GATE_NOISE_CAP} (hors catégories cibles, pas de dimension IA/business)")
        score = _GATE_NOISE_CAP
    return score, notes


def final_score(offer: dict, cfg: dict, weights: dict,
                llm: dict | None, penalties: dict | None = None) -> dict:
    comps = _components(offer, cfg, llm)
    score, breakdown = _weighted(comps, weights)

    if penalties:
        for name, pen in penalties.items():
            if name in breakdown:
                delta = min(breakdown[name]["points"], float(pen))
                breakdown[name]["points"] = round(breakdown[name]["points"] - delta, 1)
                breakdown[name]["reason"] += f" · −{delta:g} (feedback)"
                score -= delta
        score = round(score)

    adj = 0
    if llm and llm.get("score_adjustment") is not None:
        adj = max(-_LLM_ADJ_CAP, min(_LLM_ADJ_CAP, int(llm["score_adjustment"])))
        score += adj

    score = max(0, min(100, score))
    score, gate_notes = _relevance_gate(offer, cfg, comps, score)
    score, notes = _apply_hard_preferences(offer, cfg, score, comps)
    notes = gate_notes + notes

    breakdown["_llm_adjustment"] = {"points": adj, "max": _LLM_ADJ_CAP,
                                    "reason": (llm or {}).get("reasoning", "pas d'analyse LLM")}
    if notes:
        breakdown["_hard_preferences"] = {"points": 0, "max": 0, "reason": "; ".join(notes)}

    return {"score": score, "priority": priority_of(score, cfg),
            "score_breakdown": breakdown}
