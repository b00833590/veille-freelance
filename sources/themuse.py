"""The Muse — API publique (https://www.themuse.com/developers/api/v2)."""
from __future__ import annotations

import logging
import re

from sources.base import RawOffer, http_get

log = logging.getLogger("veille.sources.themuse")
_API = "https://www.themuse.com/api/public/jobs"


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ").strip()


def fetch(cfg: dict) -> list[RawOffer]:
    sc = cfg["sources"]["themuse"]
    if not sc.get("enabled", True):
        return []
    out: list[RawOffer] = []
    seen: set[str] = set()
    locations = sc.get("locations") or []
    for category in sc.get("categories", []):
        for page in range(sc.get("pages", 2)):
            params = [("category", category), ("page", page), ("descending", "true")]
            params += [("location", loc) for loc in locations]
            try:
                r = http_get(_API, params=params)
                if r.status_code != 200:
                    log.warning("themuse HTTP %s", r.status_code)
                    break
                results = r.json().get("results", [])
            except Exception as e:  # noqa: BLE001
                log.warning("themuse échec (%s / p%d): %s", category, page, type(e).__name__)
                break
            if not results:
                break
            for j in results:
                jid = str(j.get("id", ""))
                if jid in seen:
                    continue
                seen.add(jid)
                locs = ", ".join(l.get("name", "") for l in j.get("locations", []))
                out.append(RawOffer(
                    title=j.get("name", ""),
                    company=(j.get("company") or {}).get("name", ""),
                    description=_strip_html(j.get("contents", "")),
                    url=(j.get("refs") or {}).get("landing_page", ""),
                    location=locs,
                    published_at=j.get("publication_date"),
                    source="themuse",
                    external_id=jid,
                    work_time="internship" if "intern" in j.get("name", "").lower() else None,
                ))
    log.info("themuse: %d offres", len(out))
    return out
