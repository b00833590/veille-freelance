"""France Travail — API « Offres d'emploi v2 » (https://francetravail.io)."""
from __future__ import annotations

import logging
import time

import httpx

from settings import env
from sources.base import RawOffer, http_get

log = logging.getLogger("veille.sources.france_travail")

_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
_SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploiv2/offres/search"
_SCOPE = "api_offresdemploiv2 o2dsoffre"

_token: dict = {"value": None, "exp": 0.0}

_WT_MAP = {
    "temps plein": "fulltime", "temps partiel": "parttime",
}


def _get_token(client_id: str, client_secret: str) -> str | None:
    if _token["value"] and _token["exp"] > time.time() + 30:
        return _token["value"]
    try:
        r = httpx.post(_TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": _SCOPE,
        }, timeout=20.0)
        r.raise_for_status()
        j = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("france_travail: token KO: %s", type(e).__name__)
        return None
    _token["value"] = j["access_token"]
    _token["exp"] = time.time() + int(j.get("expires_in", 1200))
    return _token["value"]


def _work_time(libelle: str | None) -> str | None:
    if not libelle:
        return None
    low = libelle.lower()
    for k, v in _WT_MAP.items():
        if k in low:
            return v
    return None


def _map(o: dict) -> RawOffer:
    return RawOffer(
        title=o.get("intitule", ""),
        company=(o.get("entreprise") or {}).get("nom", "") or "",
        description=o.get("description", ""),
        url=(o.get("origineOffre") or {}).get("urlOrigine", ""),
        location=(o.get("lieuTravail") or {}).get("libelle", ""),
        published_at=o.get("dateCreation"),
        source="france_travail",
        external_id=str(o.get("id", "")),
        salary_raw=(o.get("salaire") or {}).get("libelle"),
        contract_type=o.get("typeContratLibelle") or o.get("typeContrat"),
        work_time=_work_time(o.get("dureeTravailLibelle")),
    )


def fetch(cfg: dict) -> list[RawOffer]:
    sc = cfg["sources"]["france_travail"]
    if not sc.get("enabled", True):
        return []
    cid, csecret = env("FT_CLIENT_ID"), env("FT_CLIENT_SECRET")
    if not cid or not csecret:
        log.info("france_travail désactivée (FT_CLIENT_ID/SECRET manquants)")
        return []
    token = _get_token(cid, csecret)
    if not token:
        return []

    depts = ",".join(sc.get("departements", []))
    contrats = ",".join(sc.get("type_contrat", []))
    rng = f"0-{max(0, sc.get('max_per_query', 50) - 1)}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    out: list[RawOffer] = []
    seen: set[str] = set()
    queries = [q for cat in cfg["search_queries"].values() for q in cat]
    for q in queries:
        params = {"motsCles": q, "range": rng}
        if depts:
            params["departement"] = depts
        if contrats:
            params["typeContrat"] = contrats
        try:
            r = http_get(_SEARCH_URL, params=params, headers=headers)
            if r.status_code == 204:
                continue
            if r.status_code != 200:
                log.warning("france_travail HTTP %s (%s)", r.status_code, q)
                continue
            for o in r.json().get("resultats", []):
                oid = str(o.get("id", ""))
                if oid and oid not in seen:
                    seen.add(oid)
                    out.append(_map(o))
        except Exception as e:  # noqa: BLE001
            log.warning("france_travail échec (%s): %s", q, type(e).__name__)
    log.info("france_travail: %d offres", len(out))
    return out
