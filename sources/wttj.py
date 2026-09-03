"""Welcome to the Jungle — index Algolia public. Best-effort (clés rotables sans préavis)."""
from __future__ import annotations

import logging

from urllib.parse import quote

import httpx

from sources.base import RawOffer

log = logging.getLogger("veille.sources.wttj")


def _map(hit: dict) -> RawOffer:
    org = hit.get("organization") or {}
    offices = hit.get("offices") or []
    city = ", ".join(o.get("city") or o.get("country") or "" for o in offices if o) or hit.get("_geoloc", {}).get("city", "")
    slug = hit.get("slug", "")
    org_slug = org.get("slug", "")
    url = (f"https://www.welcometothejungle.com/fr/companies/{org_slug}/jobs/{slug}"
           if org_slug and slug else hit.get("url", ""))
    contract = hit.get("contract_type") or (hit.get("contract_type_names") or [None])[0]
    return RawOffer(
        title=hit.get("name", ""),
        company=org.get("name", ""),
        description=(hit.get("profile") or "") + " " + (hit.get("description") or ""),
        url=url,
        location=city,
        published_at=hit.get("published_at"),
        source="wttj",
        external_id=str(hit.get("objectID", "")),
        contract_type=contract,
        work_time="internship" if (contract or "").lower() in ("internship", "stage") else None,
    )


def fetch(cfg: dict) -> list[RawOffer]:
    sc = cfg["sources"]["wttj"]
    if not sc.get("enabled", True):
        return []
    app_id = sc.get("algolia_app_id")
    api_key = sc.get("algolia_api_key")
    index = sc.get("index", "wttj_jobs_production_fr")
    if not app_id or not api_key:
        log.info("wttj désactivée (clés Algolia absentes)")
        return []

    url = f"https://{app_id}-dsn.algolia.net/1/indexes/{index}/query"
    headers = {"X-Algolia-Application-Id": app_id, "X-Algolia-API-Key": api_key,
               "Content-Type": "application/json"}
    hpp = sc.get("hits_per_page", 40)
    queries = [q for cat in cfg["search_queries"].values() for q in cat]

    out: list[RawOffer] = []
    seen: set[str] = set()
    for q in queries:
        body = {"params": f"query={quote(q)}&hitsPerPage={hpp}"
                          f"&filters=offices.country_code:FR"}
        try:
            r = httpx.post(url, json=body, headers=headers, timeout=20.0)
            if r.status_code != 200:
                log.warning("wttj HTTP %s — index/clé probablement périmés", r.status_code)
                return out
            hits = r.json().get("hits", [])
        except Exception as e:  # noqa: BLE001
            log.warning("wttj échec (%s): %s", q, type(e).__name__)
            return out
        for h in hits:
            oid = str(h.get("objectID", ""))
            if oid and oid not in seen:
                seen.add(oid)
                out.append(_map(h))
    log.info("wttj: %d offres", len(out))
    return out
