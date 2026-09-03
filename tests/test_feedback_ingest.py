import json

import pytest

from feedback import ingest
from settings import load_config
from store import db
from tests.conftest import make_offer

OWNER = load_config()["github"]["owner_login"]


@pytest.fixture
def offer(conn):
    o = make_offer(id="abc123", fingerprint="abc123", url="u", url_canonical="u",
                   company="BadCo", company_norm="badco", category="A",
                   score_breakdown={"missions_fit": {"points": 10, "max": 25}})
    db.upsert_offer(conn, o)
    return o


def test_parse_title():
    assert ingest.parse_title("fb:abc123:down") == ("abc123", "down")
    assert ingest.parse_title("fb: XY-9 : Applied") == ("XY-9", "applied")
    assert ingest.parse_title("random issue") is None


def test_parse_reason():
    assert ingest.parse_reason("reason: too_sales\nnote: rien") == "too_sales"
    assert ingest.parse_reason("reason: banane") == "other"
    assert ingest.parse_reason("pas de raison") is None


def test_apply_records_and_updates_status(conn, cfg, offer):
    msg = ingest.handle(conn, cfg, title="fb:abc123:down",
                        body="reason: too_technical", author=OWNER)
    assert "enregistré" in msg
    assert db.get_offer(conn, "abc123")["status"] == "ignored"
    row = conn.execute("SELECT * FROM feedback WHERE offer_id='abc123'").fetchone()
    assert row["verdict"] == "down" and row["reason"] == "too_technical"


def test_exclude_adds_company_to_greylist(conn, cfg, offer):
    ingest.handle(conn, cfg, title="fb:abc123:exclude", body="", author=OWNER)
    assert db.get_offer(conn, "abc123")["status"] == "excluded"
    assert "badco" in json.loads(db.get_state(conn, "greylist", "[]"))


def test_non_owner_rejected(conn, cfg, offer):
    msg = ingest.handle(conn, cfg, title="fb:abc123:up", body="", author="randomuser")
    assert "non autorisé" in msg
    assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0


def test_unknown_offer_handled(conn, cfg):
    msg = ingest.handle(conn, cfg, title="fb:ghost:up", body="", author=OWNER)
    assert "inconnue" in msg


def test_bad_title_handled(conn, cfg):
    msg = ingest.handle(conn, cfg, title="hello world", body="", author=OWNER)
    assert "non reconnu" in msg
