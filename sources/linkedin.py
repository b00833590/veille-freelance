"""LinkedIn — endpoint invité `jobs-guest` (pas d'API officielle). Best-effort.

Fragile depuis une IP datacenter : en cas de blocage, on renvoie []. Le filet de
sécurité est l'ingestion des alertes email LinkedIn (sources/email_inbox.py).
"""
from __future__ import annotations

import logging
import random
import time

import httpx
from selectolax.parser import HTMLParser

from sources.base import _UAS, RawOffer, http_get

log = logging.getLogger("veille.sources.linkedin")
_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
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


def _enrich_description(offer: RawOffer) -> bool:
    """Récupère la description depuis la page détail (le card n'en a pas).

    Renvoie False sur throttle (429/999) pour que l'appelant arrête l'enrichissement.
    """
    if not offer.external_id:
        return True
    try:
        r = httpx.get(_DETAIL + offer.external_id,
                      headers={**_HEADERS, "User-Agent": random.choice(_UAS)},
                      timeout=15.0, follow_redirects=True)
        if r.status_code in (429, 999):
            return False
        if r.status_code != 200:
            return True
        node = HTMLParser(r.text)
        el = (node.css_first("div.show-more-less-html__markup")
              or node.css_first("div.description__text"))
        if el:
            offer.description = el.text(separator=" ", strip=True)[:6000]
        crit = node.css_first("span.description__job-criteria-text")
        if crit:
            offer.extra["seniority"] = crit.text(strip=True)
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("linkedin enrich %s: %s", offer.external_id, type(e).__name__)
        return True


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
    stop = False
    for q in queries:
        if stop:
            break
        for page in range(pages):
            if fails >= 2:
                log.warning("linkedin: 2 échecs consécutifs, arrêt de la collecte (fallback = alertes email)")
                stop = True
                break
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

    # Enrichissement : la description n'est pas dans les cards.
    limit = sc.get("enrich_limit", 25)
    enriched = 0
    for c in out[:limit]:
        if not _enrich_description(c):
            log.warning("linkedin: throttle sur l'enrichissement, arrêt à %d", enriched)
            break
        enriched += 1
        time.sleep(sc.get("enrich_delay", 2.5))
    log.info("linkedin: %d offres (%d enrichies)", len(out), enriched)
    return out
