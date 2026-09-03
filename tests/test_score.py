from pipeline.filter_rules import classify
from pipeline.score import final_score, prescore, priority_of


def _classified(title, desc, cfg, **kw):
    o = {"title": title, "description": desc, "location": kw.pop("location", "Paris"), **kw}
    o.update(classify(o, cfg))
    o["company_norm"] = o.get("company_norm", "")
    return o


def test_founder_associate_ai_scores_high(cfg):
    o = _classified(
        "Founder Associate",
        "Startup IA early-stage. Mi-temps possible, télétravail. Business development, "
        "prospection, automatisation avec Make et n8n, création de présentations, "
        "cas d'usage IA, ChatGPT et Claude au quotidien. Aucun prérequis technique.",
        cfg, location="Remote")
    ps, breakdown = prescore(o, cfg)
    assert ps >= 65
    res = final_score(o, cfg, cfg["weights"], None)
    assert res["priority"] in (1, 2)
    # somme des points == score (pas d'ajustement LLM)
    total = sum(v["points"] for k, v in res["score_breakdown"].items()
                if not k.startswith("_"))
    assert abs(total - res["score"]) < 1.0


def test_cdi_39h_kills_student_component(cfg):
    o = _classified("Business Developer",
                    "CDI 39h par semaine, présence quotidienne du lundi au vendredi.", cfg)
    res = final_score(o, cfg, cfg["weights"], None)
    assert res["score_breakdown"]["student_compat"]["points"] <= 6
    assert res["priority"] == 3


def test_hard_pref_no_cold_calling_caps_score(cfg):
    cfg = {**cfg, "hard_preferences": {**cfg["hard_preferences"], "no_cold_calling": True}}
    o = _classified("SDR",
                    "80% du temps en cold calling et prospection téléphonique, appels sortants "
                    "toute la journée. Startup SaaS B2B, télétravail, IA pour la personnalisation.",
                    cfg, location="Remote")
    res = final_score(o, cfg, cfg["weights"], None)
    assert res["score"] <= 40


def test_llm_adjustment_is_bounded(cfg):
    o = _classified("AI Operations Intern", "Business ops, automation, no code.", cfg)
    base = final_score(o, cfg, cfg["weights"], None)["score"]
    boosted = final_score(o, cfg, cfg["weights"],
                          {"score_adjustment": 40, "reasoning": "great"})["score"]
    assert boosted - base <= 15


def test_priority_thresholds(cfg):
    assert priority_of(90, cfg) == 1
    assert priority_of(75, cfg) == 2
    assert priority_of(50, cfg) == 3


def test_senior_title_is_gated(cfg):
    o = _classified("Senior Sales Director",
                    "Lead the EMEA sales team. Business development, CRM, prospection, AI tools.",
                    cfg, location="Paris")
    assert "too_senior" in o["penalty_flags"]
    assert final_score(o, cfg, cfg["weights"], None)["score"] <= 45


def test_non_europe_location_is_gated(cfg):
    o = _classified("Business Operations Associate",
                    "Great generalist role, business dev, automation, AI, no code required.",
                    cfg, location="San Francisco, California")
    assert o["geo_ok"] is False
    assert final_score(o, cfg, cfg["weights"], None)["score"] <= 38


def test_remote_without_country_is_not_gated(cfg):
    o = _classified("Founder Associate",
                    "Remote startup, business dev, AI automation, part-time, no code.",
                    cfg, location="Remote")
    assert o["geo_ok"] is True


def test_feedback_penalties_reduce_component(cfg):
    o = _classified("Growth Associate", "Prospection, outbound, CRM, IA.", cfg)
    base = final_score(o, cfg, cfg["weights"], None)["score"]
    pen = final_score(o, cfg, cfg["weights"], None, penalties={"missions_fit": 5})["score"]
    assert pen < base
