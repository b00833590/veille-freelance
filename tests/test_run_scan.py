import pytest

from pipeline import run
from sources.base import RawOffer
from store import db


@pytest.fixture
def fake_sources(monkeypatch):
    """Remplace le registre de sources par des fausses sources contrôlées."""
    state = {"offers": []}

    def src_ok(cfg):
        return list(state["offers"])

    def src_boom(cfg):
        raise RuntimeError("source cassée")

    monkeypatch.setattr(run, "SOURCES", {"ok": src_ok, "boom": src_boom})
    monkeypatch.setattr(run, "env", lambda *a, **k: None)  # pas de LLM
    return state


def _offer(**kw):
    d = dict(title="AI Operations Intern", company="Startup X",
             description="Business dev, automation with Make and n8n, no code, part-time, remote.",
             url="https://ex.com/1", location="Paris", source="ok", external_id="1")
    d.update(kw)
    return RawOffer(**d)


def test_failing_source_does_not_break_scan(conn, cfg, fake_sources):
    fake_sources["offers"] = [_offer()]
    stats = run.scan(conn, cfg)
    assert "ok" in stats["sources_ok"]
    assert any("boom" in f for f in stats["sources_failed"])
    assert stats["n_new"] == 1


def test_duplicate_across_sources_single_row(conn, cfg, fake_sources):
    fake_sources["offers"] = [
        _offer(url="https://linkedin.com/jobs/view/1", source="linkedin"),
        _offer(url="https://adzuna.fr/land/9", source="adzuna",
               title="AI Operations Intern (H/F)"),
    ]
    run.scan(conn, cfg)
    (count,) = conn.execute("SELECT COUNT(*) FROM offers").fetchone()
    assert count == 1
    row = db.get_offer(conn, conn.execute("SELECT id FROM offers").fetchone()["id"])
    assert {s["source"] for s in row["sources"]} == {"linkedin", "adzuna"}


def test_seen_offer_not_new_on_second_scan(conn, cfg, fake_sources):
    # Test CDC 7 : offre déjà analysée ne revient pas comme "nouvelle".
    fake_sources["offers"] = [_offer()]
    s1 = run.scan(conn, cfg)
    assert s1["n_new"] == 1
    s2 = run.scan(conn, cfg)
    assert s2["n_new"] == 0


def test_ml_engineer_excluded_end_to_end(conn, cfg, fake_sources):
    # Test CDC 1.
    fake_sources["offers"] = [_offer(
        title="Machine Learning Engineer",
        description="Train and deploy ML models in production. Strong coding skills required. "
                    "Master in Machine Learning expected.")]
    run.scan(conn, cfg)
    row = conn.execute("SELECT status, priority FROM offers").fetchone()
    assert row["status"] == "excluded"


def test_old_offer_archived(conn, cfg, fake_sources):
    fake_sources["offers"] = [_offer()]
    run.scan(conn, cfg)
    conn.execute("UPDATE offers SET discovered_at = '2000-01-01T00:00:00+00:00'")
    conn.commit()
    run.scan(conn, cfg)
    assert conn.execute("SELECT archived FROM offers").fetchone()["archived"] == 1
