from pipeline import dedup
from store import db
from tests.conftest import make_offer


def test_normalize_company_strips_legal_suffix_and_accents():
    assert dedup.normalize_company("Startup X SAS") == "startup x"
    assert dedup.normalize_company("Éditions Française S.A.R.L.") == "editions francaise"


def test_normalize_title_removes_gender_and_contract_noise():
    a = dedup.normalize_title("SDR Freelance (H/F)")
    b = dedup.normalize_title("SDR - F/H")
    assert a == b == "sdr"


def test_canonical_url_drops_tracking():
    u = dedup.canonical_url("https://Example.com/jobs/1/?utm_source=li&ref=x&id=42#top")
    assert u == "https://example.com/jobs/1?id=42"


def test_fingerprint_is_stable_and_ignores_noise():
    f1 = dedup.fingerprint("Startup X SAS", "AI Ops Intern (H/F)", "Paris, France")
    f2 = dedup.fingerprint("startup x", "AI Ops Intern", "Paris")
    assert f1 == f2


def test_find_duplicate_same_url(conn):
    db.upsert_offer(conn, make_offer())
    dup = make_offer(id="other", fingerprint="other",
                     url="https://example.com/jobs/1?utm_source=x",
                     url_canonical="https://example.com/jobs/1")
    assert dedup.find_duplicate(conn, dup) == "fp-test-1"


def test_find_duplicate_cross_platform_fuzzy(conn):
    # Test 6 du CDC : LinkedIn + Adzuna, même poste, URLs différentes.
    li = make_offer(id="li1", fingerprint="li1", title="Sales Development Representative",
                    company="Acme", company_norm="acme", location="Paris",
                    url="https://linkedin.com/jobs/view/111",
                    url_canonical="https://linkedin.com/jobs/view/111")
    db.upsert_offer(conn, li)
    adz = make_offer(id="adz1", fingerprint="adz1",
                     title="Sales Development Representative (H/F)",
                     company="Acme SAS", company_norm="acme", location="Paris, FR",
                     url="https://adzuna.fr/details/222",
                     url_canonical="https://adzuna.fr/details/222")
    assert dedup.find_duplicate(conn, adz) == "li1"


def test_find_duplicate_different_role_same_company_no_match(conn):
    db.upsert_offer(conn, make_offer(id="a", fingerprint="a", title="SDR",
                                     company="Acme", company_norm="acme",
                                     url="u1", url_canonical="u1", location="Paris"))
    other = make_offer(id="b", fingerprint="b", title="Head of Growth Marketing",
                       company="Acme", company_norm="acme",
                       url="u2", url_canonical="u2", location="Paris")
    assert dedup.find_duplicate(conn, other) is None


def test_merge_sources_accumulates():
    existing = make_offer(sources=[{"source": "linkedin", "url": "a"}], salary_raw=None)
    new = make_offer(sources=[{"source": "adzuna", "url": "b"}], salary_raw="800-1200 EUR")
    merged = dedup.merge_sources(existing, new)
    got = {s["source"] for s in merged["sources"]}
    assert got == {"linkedin", "adzuna"}
    assert merged["salary_raw"] == "800-1200 EUR"
