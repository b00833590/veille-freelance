import json

from pipeline import preferences
from store import db
from tests.conftest import make_offer

_BD_REMOTE = {
    "missions_fit": {"points": 15, "max": 25},
    "student_compat": {"points": 20, "max": 25},
    "ai_business": {"points": 12, "max": 20},
    "non_technical": {"points": 12, "max": 15},
    "location": {"points": 10, "max": 10},   # composante "à fond"
    "cv_potential": {"points": 3, "max": 5},
}
_BD_ONSITE = {**_BD_REMOTE, "location": {"points": 2, "max": 10}}


def _add(conn, oid, breakdown, verdict, **over):
    o = make_offer(id=oid, fingerprint=oid, url=f"u/{oid}", url_canonical=f"u/{oid}",
                   score_breakdown=breakdown, **over)
    db.upsert_offer(conn, o)
    conn.execute("INSERT INTO feedback (offer_id, verdict, created_at) VALUES (?,?,?)",
                 (oid, verdict, "2026-09-01T00:00:00Z"))
    conn.commit()


def test_few_feedbacks_keeps_defaults(conn, cfg):
    for i in range(5):
        _add(conn, f"o{i}", _BD_REMOTE, "up")
    w = preferences.recompute_weights(conn, cfg)
    assert w == cfg["weights"]


def test_many_positive_on_remote_raises_location_weight_bounded(conn, cfg):
    # 20 feedbacks "up" sur des offres où la composante location est maximale.
    for i in range(20):
        _add(conn, f"o{i}", _BD_REMOTE, "up")
    w = preferences.recompute_weights(conn, cfg)
    assert abs(sum(w.values()) - 100) < 0.5
    assert w["location"] > cfg["weights"]["location"]
    assert w["location"] - cfg["weights"]["location"] <= 2.5  # nudge borné (~±2 avant renorm)


def test_current_weights_returns_last_snapshot(conn, cfg):
    conn.execute("INSERT INTO pref_weights (snapshot_at, weights, feedback_count, confidence) "
                 "VALUES (?,?,?,?)", ("2026-09-01T00:00:00Z", json.dumps({"missions_fit": 40}), 50, "high"))
    conn.commit()
    assert preferences.current_weights(conn, cfg)["missions_fit"] == 40


def test_explain_match_finds_liked_company(conn):
    _add(conn, "liked1", _BD_REMOTE, "up", company="Acme", company_norm="acme",
         category="A", remote="remote", work_time="freelance")
    offer = make_offer(company="Acme", company_norm="acme", category="A",
                       remote="remote", work_time="freelance")
    phrases = preferences.explain_match(conn, offer)
    assert any("Acme" in p for p in phrases)


def test_feedback_penalties_from_reasons(conn, cfg):
    for i in range(3):
        o = f"r{i}"
        db.upsert_offer(conn, make_offer(id=o, fingerprint=o, url=f"u{o}", url_canonical=f"u{o}"))
        conn.execute("INSERT INTO feedback (offer_id, verdict, reason, created_at) VALUES (?,?,?,?)",
                     (o, "down", "too_sales", "2026-09-01T00:00:00Z"))
    conn.commit()
    pen = preferences.feedback_penalties(conn, cfg)
    assert pen.get("missions_fit", 0) >= 5
