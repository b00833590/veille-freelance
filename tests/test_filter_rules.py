from pipeline.filter_rules import classify, detect_category, is_excluded


def _o(title, desc="", location="Paris", **kw):
    return {"title": title, "description": desc, "location": location, **kw}


# --- Test CDC 1 : ML Engineer rejeté -----------------------------------------
def test_ml_engineer_excluded(cfg):
    o = _o("Machine Learning Engineer",
           "You will train models in production, strong coding skills required.")
    res = classify(o, cfg)
    assert res["excluded"] is True
    assert res["status"] == "excluded"


def test_data_scientist_excluded(cfg):
    assert is_excluded(_o("Senior Data Scientist", "PhD in Statistics preferred"), cfg)[0]


def test_ai_ops_not_excluded_despite_ai_keyword(cfg):
    o = _o("AI Operations Intern",
           "Set up AI workflows with Make and n8n, business development, no coding required.")
    res = classify(o, cfg)
    assert res["excluded"] is False
    assert res["category"] == "A"


# --- Test CDC 2 : SDR freelance remote --------------------------------------
def test_sdr_freelance_remote(cfg):
    o = _o("Sales Development Representative",
           "Freelance mission, 100% remote. Cold calling, prospection LinkedIn, qualification de leads.",
           location="Remote")
    res = classify(o, cfg)
    assert res["category"] == "B"
    assert res["remote"] == "remote"
    assert res["work_time"] == "freelance"
    assert res["excluded"] is False


# --- Test CDC 4 : consultant IA junior non technique -----------------------
def test_ai_consultant_junior(cfg):
    o = _o("Consultant IA junior",
           "Animation d'ateliers IA, accompagnement au changement, aucun prérequis technique. "
           "Formation ChatGPT et Claude pour les collaborateurs.")
    res = classify(o, cfg)
    assert res["category"] == "C"
    assert res["excluded"] is False


# --- Test CDC 5 : CDI 39h -------------------------------------------------
def test_cdi_full_time_penalised(cfg):
    o = _o("Business Developer",
           "CDI 39h par semaine, présence du lundi au vendredi au bureau.")
    res = classify(o, cfg)
    assert "full_time" in res["penalty_flags"]
    assert res["student_arrangement"] is False
    assert res["work_time"] == "fulltime"


def test_student_arrangement_detected(cfg):
    o = _o("Founder Associate",
           "Temps plein, mais aménagement étudiant possible et compatible avec les études.")
    res = classify(o, cfg)
    assert res["student_arrangement"] is True


def test_detect_category_unknown_when_weak(cfg):
    cat, score = detect_category("Office manager assistant polyvalent", cfg)
    assert cat == "UNKNOWN"


def test_hours_detection(cfg):
    res = classify(_o("Growth intern", "20h par semaine, mi-temps"), cfg)
    assert res["work_time_hours"] == 20
    assert res["work_time"] in ("parttime", "internship")
