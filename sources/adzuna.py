"""Adzuna — API publique (https://developer.adzuna.com)."""
from __future__ import annotations

import logging

from settings import env
from sources.base import RawOffer, http_get

log = logging.getLogger("veille.sources.adzuna")
_BASE = "https://api.adzuna.com/v1/api/jobs"

_CONTRACT_TIME = {"full_time": "fulltime", "part_time": "parttime"}


def _map(j: dict) -> RawOffer:
    sal = None
    if j.get("salary_min"):
        sal = f'{int(j["salary_min"])}-{int(j.get("salary_max") or j["salary_min"])} EUR/an'
    return RawOffer(
        title=j.get("title", ""),
        company=(j.get("company") or {}).get("display_name", ""),
        description=j.get("description", ""),
        url=j.get("redirect_url", ""),
        location=(j.get("location") or {}).get("display_name", ""),
        published_at=j.get("created"),
        source="adzuna",
        external_id=str(j.get("id", "")),
        salary_raw=sal,
        contract_type=j.get("contract_type"),
        work_time=_CONTRACT_TIME.get(j.get("contract_time")),
    )


def fetch(cfg: dict) -> list[RawOffer]:
    sc = cfg["sources"]["adzuna"]
    if not sc.get("enabled", True):
        return []
    app_id, app_key = env("ADZUNA_APP_ID"), env("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        log.info("adzuna désactivée (ADZUNA_APP_ID/KEY manquants)")
        return []

    country = sc.get("country", "fr")
    common = {
        "app_id": app_id, "app_key": app_key,
        "results_per_page": sc.get("results_per_page", 50),
        "max_days_old": sc.get("max_days_old", 30),
        "content-type": "application/json",
    }
    queries = [q for cat in cfg["search_queries"].values() for q in cat]
    # 2 passes : Paris on-site + remote/télétravail.
    passes = [{"where": sc.get("where", "Paris")},
              {"what_and": "remote"}, {"what_and": "télétravail"}]

    out: list[RawOffer] = []
    seen: set[str] = set()
    for q in queries:
        for extra in passes:
            for page in range(1, sc.get("pages", 2) + 1):
                params = {**common, "what": q, **extra}
                try:
                    r = http_get(f"{_BASE}/{country}/search/{page}", params=params)
                    if r.status_code != 200:
                        if r.status_code in (400, 401):
                            log.warning("adzuna HTTP %s — vérifie les clés", r.status_code)
                            return out
                        break
                    results = r.json().get("results", [])
                except Exception as e:  # noqa: BLE001
                    log.warning("adzuna échec (%s): %s", q, type(e).__name__)
                    break
                if not results:
                    break
                for j in results:
                    jid = str(j.get("id", ""))
                    if jid and jid not in seen:
                        seen.add(jid)
                        out.append(_map(j))
    log.info("adzuna: %d offres", len(out))
    return out
