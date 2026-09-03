import httpx
import pytest

from sources import linkedin, wttj

LINKEDIN_HTML = """
<li>
  <div class="base-card relative">
    <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/founder-associate-at-acme-3920011?trk=x"
       data-entity-urn="urn:li:jobPosting:3920011"></a>
    <h3 class="base-search-card__title">Founder Associate</h3>
    <h4 class="base-search-card__subtitle">Acme</h4>
    <span class="job-search-card__location">Paris, Île-de-France, France</span>
    <time class="job-search-card__listdate" datetime="2026-08-30">3 days ago</time>
  </div>
</li>
<li>
  <div class="base-card">
    <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/sdr-at-beta-3920022"
       data-entity-urn="urn:li:jobPosting:3920022"></a>
    <h3 class="base-search-card__title">Sales Development Representative</h3>
    <h4 class="base-search-card__subtitle">Beta</h4>
    <span class="job-search-card__location">Remote, France</span>
  </div>
</li>
"""


class FakeResp:
    def __init__(self, text="", status=200, payload=None):
        self.text, self.status_code, self._p = text, status, payload

    def json(self):
        return self._p


def _cfg(base, name, over):
    c = dict(base)
    c["sources"] = {**base["sources"], name: over}
    return c


def test_linkedin_parses_cards(cfg, monkeypatch):
    seq = [FakeResp(LINKEDIN_HTML)] + [FakeResp("")] * 50
    monkeypatch.setattr(linkedin, "http_get", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(linkedin.time, "sleep", lambda *_: None)
    offers = linkedin.fetch(_cfg(cfg, "linkedin",
                                 {"enabled": True, "location": "France", "pages": 1,
                                  "time_filter": "r604800", "delay_seconds": 0, "enrich_limit": 0}))
    assert {o.title for o in offers} == {"Founder Associate", "Sales Development Representative"}
    fa = next(o for o in offers if o.title == "Founder Associate")
    assert fa.company == "Acme" and fa.external_id == "3920011"
    assert fa.published_at == "2026-08-30"


def test_linkedin_enrichment_fills_description(cfg, monkeypatch):
    seq = [FakeResp(LINKEDIN_HTML)] + [FakeResp("")] * 50
    monkeypatch.setattr(linkedin, "http_get", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(linkedin.time, "sleep", lambda *_: None)
    detail = '<div class="show-more-less-html__markup">Prospection, cold calling, CRM, IA pour la personnalisation.</div>'
    monkeypatch.setattr(linkedin.httpx, "get", lambda *a, **k: FakeResp(detail))
    offers = linkedin.fetch(_cfg(cfg, "linkedin",
                                 {"enabled": True, "pages": 1, "delay_seconds": 0,
                                  "enrich_limit": 5, "enrich_delay": 0}))
    assert any("cold calling" in (o.description or "") for o in offers)


def test_linkedin_blocked_returns_partial(cfg, monkeypatch):
    monkeypatch.setattr(linkedin, "http_get", lambda *a, **k: FakeResp("", status=999))
    monkeypatch.setattr(linkedin.time, "sleep", lambda *_: None)
    assert linkedin.fetch(_cfg(cfg, "linkedin", {"enabled": True, "pages": 3, "delay_seconds": 0})) == []


def test_wttj_maps_hits(cfg, monkeypatch):
    payload = {"hits": [{
        "objectID": "job_1", "name": "AI Enablement Consultant",
        "organization": {"name": "ConseilIA", "slug": "conseil-ia"},
        "offices": [{"city": "Paris", "country": "France"}],
        "slug": "ai-enablement-consultant", "published_at": "2026-09-01",
        "contract_type": "FULL_TIME", "profile": "Former les équipes à l'IA",
    }]}
    monkeypatch.setattr(wttj.httpx, "post", lambda *a, **k: FakeResp(payload=payload))
    offers = wttj.fetch(_cfg(cfg, "wttj", {"enabled": True, "algolia_app_id": "APP",
                                           "algolia_api_key": "KEY", "index": "idx",
                                           "hits_per_page": 10}))
    assert offers[0].company == "ConseilIA"
    assert offers[0].url.endswith("/companies/conseil-ia/jobs/ai-enablement-consultant")


def test_wttj_403_returns_empty(cfg, monkeypatch):
    monkeypatch.setattr(wttj.httpx, "post", lambda *a, **k: FakeResp(status=403))
    assert wttj.fetch(_cfg(cfg, "wttj", {"enabled": True, "algolia_app_id": "A",
                                         "algolia_api_key": "K"})) == []


def test_wttj_disabled_without_keys(cfg):
    assert wttj.fetch(_cfg(cfg, "wttj", {"enabled": True})) == []
