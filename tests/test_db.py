from store import db
from tests.conftest import make_offer


def test_init_db_creates_tables(conn):
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert {"offers", "feedback", "pref_weights", "runs", "state"} <= names


def test_upsert_offer_new_then_existing(conn):
    oid, is_new = db.upsert_offer(conn, make_offer())
    assert is_new is True
    assert oid == "fp-test-1"

    # Deuxième upsert, même fingerprint => pas nouveau, pas de doublon.
    oid2, is_new2 = db.upsert_offer(conn, make_offer(title="AI Operations Intern (H/F)"))
    assert is_new2 is False
    assert oid2 == "fp-test-1"
    (count,) = conn.execute("SELECT COUNT(*) FROM offers").fetchone()
    assert count == 1

    row = db.get_offer(conn, "fp-test-1")
    assert row["title"] == "AI Operations Intern (H/F)"        # champ mis à jour
    assert isinstance(row["sources"], list)                    # JSON décodé


def test_discovered_at_not_overwritten(conn):
    db.upsert_offer(conn, make_offer())
    first = db.get_offer(conn, "fp-test-1")["discovered_at"]
    db.upsert_offer(conn, make_offer(discovered_at="2099-01-01T00:00:00+00:00"))
    assert db.get_offer(conn, "fp-test-1")["discovered_at"] == first


def test_state_roundtrip(conn):
    assert db.get_state(conn, "x") is None
    assert db.get_state(conn, "x", "def") == "def"
    db.set_state(conn, "x", "1")
    assert db.get_state(conn, "x") == "1"
    db.set_state(conn, "x", "2")
    assert db.get_state(conn, "x") == "2"


def test_record_run(conn):
    rid = db.record_run(conn, {"n_raw": 10, "n_new": 3, "sources_ok": ["themuse"]})
    assert rid == 1
    row = conn.execute("SELECT * FROM runs WHERE id = 1").fetchone()
    assert row["n_raw"] == 10 and row["n_new"] == 3
