import pytest

from notify import alert, email_digest, mailer
from store import db
from tests.conftest import make_offer

_BD = {"missions_fit": {"points": 20, "max": 25, "reason": "cat A"},
       "student_compat": {"points": 22, "max": 25, "reason": "temps partiel"},
       "ai_business": {"points": 16, "max": 20, "reason": "IA + business"},
       "non_technical": {"points": 13, "max": 15, "reason": "pas de code"},
       "location": {"points": 9, "max": 10, "reason": "remote"},
       "cv_potential": {"points": 4, "max": 5, "reason": "startup"}}


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(mailer, "send_mail", lambda s, h, **k: box.append((s, h)) or True)
    monkeypatch.setattr(email_digest, "send_mail", mailer.send_mail)
    monkeypatch.setattr(alert, "send_mail", mailer.send_mail)
    return box


def test_digest_includes_high_excludes_low(conn, cfg, sent):
    db.upsert_offer(conn, make_offer(id="hi", fingerprint="hi", url="u/hi", url_canonical="u/hi",
                                     score=90, priority=1, category="A", score_breakdown=_BD))
    db.upsert_offer(conn, make_offer(id="mid", fingerprint="mid", url="u/mid", url_canonical="u/mid",
                                     score=74, priority=2, category="B", score_breakdown=_BD))
    db.upsert_offer(conn, make_offer(id="lo", fingerprint="lo", url="u/lo", url_canonical="u/lo",
                                     score=55, priority=3, category="A", score_breakdown=_BD))
    total = email_digest.send(conn, cfg)
    assert total == 2
    subject, html = sent[-1]
    assert "hi" in html or "AI Operations Intern" in html
    assert "u/lo" not in html
    assert db.get_state(conn, "last_digest_at") is not None


def test_digest_respects_max_items(conn, cfg, sent):
    cfg = {**cfg, "digest": {**cfg["digest"], "max_items": 3, "explore_ratio": 0.0}}
    for i in range(6):
        db.upsert_offer(conn, make_offer(id=f"o{i}", fingerprint=f"o{i}", url=f"u/{i}",
                                         url_canonical=f"u/{i}", score=88, priority=1,
                                         category="A", score_breakdown=_BD))
    email_digest.send(conn, cfg)
    _, html = sent[-1]
    assert html.count('class="card"') == 3


def test_digest_empty_still_sends_ras(conn, cfg, sent):
    assert email_digest.send(conn, cfg) == 0
    assert "rien de neuf" in sent[-1][0]


def test_alert_not_sent_twice(conn, cfg, sent):
    db.upsert_offer(conn, make_offer(id="fire", fingerprint="fire", url="u/f", url_canonical="u/f",
                                     score=92, priority=1, category="A", score_breakdown=_BD))
    assert alert.maybe_send(conn, cfg, ["fire"]) == 1
    assert alert.maybe_send(conn, cfg, ["fire"]) == 0  # déjà alertée
    assert len([s for s in sent if s[0].startswith("🔥")]) == 1


def test_mailer_without_creds_returns_false(monkeypatch):
    monkeypatch.setattr(mailer, "env", lambda *a, **k: None)
    assert mailer.send_mail("s", "<p>h</p>") is False
