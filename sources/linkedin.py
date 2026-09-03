"""LinkedIn — endpoint invité `jobs-guest` (pas d'API officielle). Best-effort.

Fragile depuis une IP datacenter : en cas de blocage, on renvoie []. Le filet de
sécurité est l'ingestion des alertes email LinkedIn (sources/email_inbox.py).
"""
from __future__ import annotations

import logging
import time

from selectolax.parser import HTMLParser

from sources.base import RawOffer, http_get

log = logging.getLogger("veille.sources.linkedin")
_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.linkedin.com/jobs",
}


def _txt(node, sel: str) -> str:
    el = node.css_first(sel)
    return el.text(strip=True) if el else ""


def _parse(html: str) -> list[RawOffer]:
    out: list[RawOffer] = []
    for card in HTMLParser(html).css("li"):
        base = card.css_first("div.base-card") or card.css_first("div.base-search-card")
        if base is None:
            continue
        link = card.css_first("a.base-card__full-link") or card.css_first("a.base-search-card__full-link")
        href = (link.attributes.get("href") if link else "") or ""
        href = href.split("?")[0]
        title = _txt(card, "h3.base-search-card__title")
        company = _txt(card, "h4.base-search-card__subtitle")
        loc = _txt(card, "span.job-search-card__location")
        tnode = card.css_first("time")
        published = (tnode.attributes.get("datetime") if tnode else None) or None
        entity = ""
        if link and (di := link.attributes.get("data-entity-urn")):
            entity = di.split(":")[-1]
        elif "/view/" in href:
            entity = href.rstrip("/").split("-")[-1]
        if title and href:
            out.append(RawOffer(
                title=title, company=company, description="", url=href, location=loc,
                published_at=published, source="linkedin", external_id=entity,
            ))
    return out


def fetch(cfg: dict) -> list[RawOffer]:
    sc = cfg["sources"]["linkedin"]
    if not sc.get("enabled", True):
        return []
    location = sc.get("location", "France")
    tpr = sc.get("time_filter", "r604800")
    pages = sc.get("pages", 3)
    delay = sc.get("delay_seconds", 3)

    queries = [q for cat in cfg["search_queries"].values() for q in cat]
    out: list[RawOffer] = []
    seen: set[str] = set()
    fails = 0
    for q in queries:
        for page in range(pages):
            if fails >= 2:
                log.warning("linkedin: 2 échecs consécutifs, arrêt (fallback = alertes email)")
                return out
            params = {"keywords": q, "location": location, "f_TPR": tpr,
                      "start": page * 25}
            try:
                r = http_get(_URL, params=params, headers=_HEADERS)
                if r.status_code != 200 or not r.text.strip():
                    fails += 1
                    break
                fails = 0
            except Exception as e:  # noqa: BLE001
                log.warning("linkedin échec (%s p%d): %s", q, page, type(e).__name__)
                fails += 1
                break
            cards = _parse(r.text)
            if not cards:
                break
            for c in cards:
                key = c.external_id or c.url
                if key not in seen:
                    seen.add(key)
                    out.append(c)
            time.sleep(delay)
    log.info("linkedin: %d offres", len(out))
    return out
