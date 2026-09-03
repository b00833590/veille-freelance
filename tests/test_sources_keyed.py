import httpx
import pytest

from sources import adzuna, france_travail


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("e", request=None, response=None)


def _cfg(base, name, over):
    c = dict(base)
    c["sources"] = {**base["sources"], name: over}
    return c


# --------------------------- France Travail --------------------------------
def test_ft_disabled_without_keys(cfg, monkeypatch):
    monkeypatch.setattr(france_travail, "env", lambda *a, **k: None)
    assert france_travail.fetch(_cfg(cfg, "france_travail", {"enabled": True})) == []


def test_ft_maps_and_dedups(cfg, monkeypatch):
    monkeypatch.setattr(france_travail, "env",
                        lambda n, d=None: {"FT_CLIENT_ID": "id", "FT_CLIENT_SECRET": "s"}.get(n, d))
    monkeypatch.setattr(france_travail, "_get_token", lambda *a: "tok")
    result = {"resultats": [{
        "id": "ABC123", "intitule": "Assistant Business Development & IA",
        "entreprise": {"nom": "FinTechCo"}, "lieuTravail": {"libelle": "75 - Paris"},
        "description": "Prospection, propositions commerciales, automatisation.",
        "dateCreation": "2026-09-01T08:00:00Z", "typeContratLibelle": "MIS",
        "dureeTravailLibelle": "Temps partiel", "salaire": {"libelle": "Selon profil"},
        "origineOffre": {"urlOrigine": "https://candidat.francetravail.fr/offres/ABC123"},
    }]}
    monkeypatch.setattr(france_travail, "http_get", lambda *a, **k: FakeResp(result))
    offers = france_travail.fetch(_cfg(cfg, "france_travail",
                                       {"enabled": True, "departements": ["75"],
                                        "type_contrat": ["MIS"], "max_per_query": 20}))
    assert len(offers) == 1  # même id renvoyé pour chaque requête -> dédupliqué
    assert offers[0].work_time == "parttime"
    assert offers[0].company == "FinTechCo"


def test_ft_204_no_content(cfg, monkeypatch):
    monkeypatch.setattr(france_travail, "env", lambda n, d=None: "x")
    monkeypatch.setattr(france_travail, "_get_token", lambda *a: "tok")
    monkeypatch.setattr(france_travail, "http_get", lambda *a, **k: FakeResp({}, status=204))
    assert france_travail.fetch(_cfg(cfg, "france_travail", {"enabled": True})) == []


# ------------------------------- Adzuna -----------------------------------
def test_adzuna_disabled_without_keys(cfg, monkeypatch):
    monkeypatch.setattr(adzuna, "env", lambda *a, **k: None)
    assert adzuna.fetch(_cfg(cfg, "adzuna", {"enabled": True})) == []


def test_adzuna_maps_fields(cfg, monkeypatch):
    monkeypatch.setattr(adzuna, "env", lambda n, d=None: "key")
    payload = {"results": [{
        "id": "9", "title": "Growth Intern", "company": {"display_name": "SaaSCo"},
        "location": {"display_name": "Paris, Île-de-France"},
        "description": "Outbound, growth, IA.", "created": "2026-08-29T00:00:00Z",
        "redirect_url": "https://adzuna.fr/land/9", "salary_min": 24000, "salary_max": 30000,
        "contract_time": "part_time", "contract_type": "contract",
    }]}
    seq = [FakeResp(payload)] + [FakeResp({"results": []})] * 30
    monkeypatch.setattr(adzuna, "http_get", lambda *a, **k: seq.pop(0))
    offers = adzuna.fetch(_cfg(cfg, "adzuna", {"enabled": True, "pages": 1}))
    assert offers and offers[0].work_time == "parttime"
    assert "24000" in offers[0].salary_raw


def test_adzuna_bad_key_aborts(cfg, monkeypatch):
    monkeypatch.setattr(adzuna, "env", lambda n, d=None: "key")
    monkeypatch.setattr(adzuna, "http_get", lambda *a, **k: FakeResp({}, status=401))
    assert adzuna.fetch(_cfg(cfg, "adzuna", {"enabled": True})) == []
