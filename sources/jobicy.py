"""Jobicy — API publique v2 (https://jobicy.com/jobs-rss-feed)."""
from __future__ import annotations

import logging
import re

from sources.base import RawOffer, http_get

log = logging.getLogger("veille.sources.jobicy")
_API = "https://jobicy.com/api/v2/remote-jobs"

# Industries Jobicy valides et pertinentes pour les 3 catégories.
_INDUSTRIES = ["business", "marketing", "management", "admin", "supporting", "hr"]


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ").strip()


def fetch(cfg: dict) -> list[RawOffer]:
    sc = cfg["sources"]["jobicy"]
    if not sc.get("enabled", True):
        return []
    count = sc.get("count", 50)
    geo = sc.get("geo", "europe")
    out: list[RawOffer] = []
    seen: set[str] = set()
    for industry in _INDUSTRIES:
        try:
            r = http_get(_API, params={"count": count, "geo": geo, "industry": industry})
            if r.status_code != 200:
                log.warning("jobicy HTTP %s", r.status_code)
                continue
            jobs = r.json().get("jobs", [])
        except Exception as e:  # noqa: BLE001
            log.warning("jobicy échec (%s): %s", industry, type(e).__name__)
            continue
        for j in jobs:
            jid = str(j.get("id", ""))
            if jid in seen:
                continue
            seen.add(jid)
            out.append(RawOffer(
                title=j.get("jobTitle", ""),
                company=j.get("companyName", ""),
                description=_strip_html(j.get("jobExcerpt", "") or j.get("jobDescription", "")),
                url=j.get("url", ""),
                location=j.get("jobGeo", "") or "Remote",
                published_at=j.get("pubDate"),
                source="jobicy",
                external_id=jid,
                salary_raw=(f'{j.get("annualSalaryMin")}-{j.get("annualSalaryMax")} '
                            f'{j.get("salaryCurrency", "")}').strip()
                if j.get("annualSalaryMin") else None,
                work_time=(j.get("jobType") or [None])[0] if isinstance(j.get("jobType"), list)
                else j.get("jobType"),
            ))
    log.info("jobicy: %d offres", len(out))
    return out
