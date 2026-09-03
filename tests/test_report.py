import json

from report import build_html
from store import db
from tests.conftest import make_offer

_BD = {"missions_fit": {"points": 20, "max": 25, "reason": "cat A"},
       "location": {"points": 9, "max": 10, "reason": "remote"}}


def test_build_creates_files_and_data(conn, cfg, tmp_path):
    db.upsert_offer(conn, make_offer(id="o1", fingerprint="o1", url="https://ex.com/1",
                                     url_canonical="https://ex.com/1", score=88, priority=1,
                                     category="A", score_breakdown=_BD))
    db.upsert_offer(conn, make_offer(id="o2", fingerprint="o2", url="https://ex.com/2",
                                     url_canonical="https://ex.com/2", score=40, priority=3,
                                     category="B", score_breakdown=_BD, archived=1))
    build_html.build(conn, cfg, out_dir=str(tmp_path))

    assert (tmp_path / "index.html").exists()
    data = json.loads((tmp_path / "data.json").read_text(encoding="utf-8"))
    ids = [o["id"] for o in data["offers"]]
    assert ids == ["o1"]                       # archivée exclue
    assert "stats" in data and data["stats"]["analysed"] == 2


def test_feedback_links_use_owner_repo(conn, cfg, tmp_path):
    db.upsert_offer(conn, make_offer(id="abc", fingerprint="abc", url="u", url_canonical="u",
                                     score=90, priority=1, score_breakdown=_BD))
    build_html.build(conn, cfg, out_dir=str(tmp_path))
    data = json.loads((tmp_path / "data.json").read_text(encoding="utf-8"))
    up = data["offers"][0]["feedback"]["up"]
    assert "github.com/harryrouas/veille-freelance/issues/new" in up
    assert "title=fb:abc:up" in up


def test_stats_counts_feedback_and_applications(conn, cfg, tmp_path):
    db.upsert_offer(conn, make_offer(id="x", fingerprint="x", url="u", url_canonical="u",
                                     category="A", score_breakdown=_BD))
    conn.execute("INSERT INTO feedback (offer_id, verdict, reason, created_at) VALUES "
                 "('x','applied',NULL,'2026-09-01'),('x','up','too_sales','2026-09-01')")
    conn.commit()
    build_html.build(conn, cfg, out_dir=str(tmp_path))
    s = json.loads((tmp_path / "data.json").read_text(encoding="utf-8"))["stats"]
    assert s["applications"] == 1
    assert s["feedback_count"] == 2
    assert s["reject_reasons"].get("too_sales") == 1
