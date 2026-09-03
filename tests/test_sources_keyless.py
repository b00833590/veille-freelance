"""Chaque source keyless : mapping correct + robustesse aux erreurs HTTP."""
import httpx
import pytest

from sources import hn_whoishiring, jobicy, remotive, themuse


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _cfg(base_cfg, **src_over):
    c = dict(base_cfg)
    c["sources"] = {**base_cfg["sources"], **src_over}
    return c


# --------------------------------------------------------------------------- #
def test_themuse_maps_fields(cfg, monkeypatch):
    payload = {"results": [{
        "id": 42, "name": "Business Operations Intern",
        "company": {"name": "Acme"},
        "locations": [{"name": "Paris, France"}],
        "refs": {"landing_page": "https://themuse.com/jobs/42"},
        "contents": "<p>Great <b>role</b></p>",
        "publication_date": "2026-09-01T00:00:00Z",
    }]}
    calls = {"n": 0}

    def fake(url, **kw):
        calls["n"] += 1
        return FakeResp(payload if calls["n"] == 1 else {"results": []})

    monkeypatch.setattr(themuse, "http_get", fake)
    offers = themuse.fetch(_cfg(cfg, themuse={"enabled": True, "categories": ["Business Operations"], "pages": 2}))
    assert len(offers) == 1
    o = offers[0]
    assert o.company == "Acme" and o.location == "Paris, France"
    assert "<" not in o.description and o.work_time == "internship"
    assert o.source == "themuse"


def test_themuse_http_error_returns_empty(cfg, monkeypatch):
    monkeypatch.setattr(themuse, "http_get",
                        lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("boom")))
    assert themuse.fetch(_cfg(cfg, themuse={"enabled": True, "categories": ["Sales"], "pages": 1})) == []


# --------------------------------------------------------------------------- #
def test_remotive_maps_fields(cfg, monkeypatch):
    payload = {"jobs": [{
        "id": 7, "title": "Sales Development Representative",
        "company_name": "RemoteCo", "candidate_required_location": "Europe",
        "url": "https://remotive.com/j/7", "description": "<div>Cold calling</div>",
        "publication_date": "2026-08-30", "salary": "40k-50k", "job_type": "freelance",
    }]}
    monkeypatch.setattr(remotive, "http_get", lambda *a, **k: FakeResp(payload))
    offers = remotive.fetch(_cfg(cfg, remotive={"enabled": True, "limit_per_query": 5}))
    assert offers and offers[0].contract_type == "freelance"
    assert offers[0].salary_raw == "40k-50k"


def test_remotive_500_returns_empty(cfg, monkeypatch):
    monkeypatch.setattr(remotive, "http_get", lambda *a, **k: FakeResp({}, status=500))
    assert remotive.fetch(_cfg(cfg, remotive={"enabled": True})) == []


# --------------------------------------------------------------------------- #
def test_jobicy_maps_fields(cfg, monkeypatch):
    payload = {"jobs": [{
        "id": 99, "jobTitle": "Growth Associate", "companyName": "GrowthLab",
        "jobGeo": "Europe", "url": "https://jobicy.com/j/99",
        "jobExcerpt": "Outbound & growth", "pubDate": "2026-09-02",
        "jobType": ["full-time"], "annualSalaryMin": 30000, "annualSalaryMax": 45000,
        "salaryCurrency": "EUR",
    }]}
    monkeypatch.setattr(jobicy, "http_get", lambda *a, **k: FakeResp(payload))
    offers = jobicy.fetch(_cfg(cfg, jobicy={"enabled": True, "count": 10, "geo": "europe"}))
    assert offers and offers[0].company == "GrowthLab"
    assert "30000" in offers[0].salary_raw and offers[0].work_time == "full-time"


# --------------------------------------------------------------------------- #
def test_hn_parses_hiring_comments(cfg, monkeypatch):
    search_payload = {"hits": [{"objectID": "111", "title": "Ask HN: Who is hiring? (September 2026)"}]}
    item_payload = {"children": [
        {"id": 1, "created_at": "2026-09-01T10:00:00Z",
         "text": "Acme (Paris, Remote OK) | Founder Associate | full-time or part-time<p>"
                 "Join our early-stage startup. https://acme.com/jobs Business development and AI ops."},
        {"id": 2, "text": "short"},
    ]}

    def fake(url, **kw):
        return FakeResp(search_payload if "search_by_date" in url else item_payload)

    monkeypatch.setattr(hn_whoishiring, "http_get", fake)
    offers = hn_whoishiring.fetch(_cfg(cfg, hn_whoishiring={"enabled": True, "max_comments": 50}))
    assert len(offers) == 1
    assert offers[0].company.startswith("Acme")
    assert offers[0].url == "https://acme.com/jobs"


def test_hn_network_error_returns_empty(cfg, monkeypatch):
    monkeypatch.setattr(hn_whoishiring, "http_get",
                        lambda *a, **k: (_ for _ in ()).throw(httpx.ReadTimeout("t")))
    assert hn_whoishiring.fetch(_cfg(cfg, hn_whoishiring={"enabled": True})) == []
