"""Remotive — API publique (https://remotive.com/api/remote-jobs)."""
from __future__ import annotations

import logging
import re

from sources.base import RawOffer, http_get

log = logging.getLogger("veille.sources.remotive")
_API = "https://remotive.com/api/remote-jobs"


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ").strip()


def _all_queries(cfg: dict) -> list[str]:
    qs: list[str] = []
    for cat in cfg["search_queries"].values():
        qs.extend(cat)
    return qs


def fetch(cfg: dict) -> list[RawOffer]:
    sc = cfg["sources"]["remotive"]
    if not sc.get("enabled", True):
        return []
    limit = sc.get("limit_per_query", 40)
    out: list[RawOffer] = []
    seen: set[str] = set()
    for q in _all_queries(cfg):
        try:
            r = http_get(_API, params={"search": q, "limit": limit})
            if r.status_code != 200:
                log.warning("remotive HTTP %s", r.status_code)
                continue
            jobs = r.json().get("jobs", [])
        except Exception as e:  # noqa: BLE001
            log.warning("remotive échec (%s): %s", q, type(e).__name__)
            continue
        for j in jobs:
            jid = str(j.get("id", ""))
            if jid in seen:
                continue
            seen.add(jid)
            out.append(RawOffer(
                title=j.get("title", ""),
                company=j.get("company_name", ""),
                description=_strip_html(j.get("description", "")),
                url=j.get("url", ""),
                location=j.get("candidate_required_location", "") or "Remote",
                published_at=j.get("publication_date"),
                source="remotive",
                external_id=jid,
                salary_raw=j.get("salary") or None,
                contract_type=j.get("job_type") or None,
            ))
    log.info("remotive: %d offres", len(out))
    return out
