"""Hacker News « Ask HN: Who is hiring? » via l'API Algolia HN (gratuite, sans clé)."""
from __future__ import annotations

import logging
import re

from sources.base import RawOffer, http_get

log = logging.getLogger("veille.sources.hn")
_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
_ITEM = "https://hn.algolia.com/api/v1/items/"

_URL_RX = re.compile(r"https?://[^\s\"<>]+")


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    for a, b in (("&#x2F;", "/"), ("&#x27;", "'"), ("&quot;", '"'), ("&amp;", "&"), ("&gt;", ">"), ("&lt;", "<")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _keywords(cfg: dict) -> list[str]:
    # Uniquement les intitulés cibles précis : HN est trop volumineux pour du large.
    kw = {"chief of staff", "founder associate", "founding gtm", "founding bdr",
          "founder's associate", "generalist"}
    for cat in cfg["search_queries"].values():
        kw.update(q.lower() for q in cat if len(q) > 4)
    return sorted(kw)


def _latest_thread_id() -> str | None:
    r = http_get(_SEARCH, params={"tags": "story,author_whoishiring",
                                  "query": "Ask HN: Who is hiring", "hitsPerPage": 5})
    for hit in r.json().get("hits", []):
        if "who is hiring" in (hit.get("title", "") or "").lower():
            return hit.get("objectID")
    return None


def fetch(cfg: dict) -> list[RawOffer]:
    sc = cfg["sources"]["hn_whoishiring"]
    if not sc.get("enabled", True):
        return []
    try:
        tid = _latest_thread_id()
        if not tid:
            log.warning("hn: thread introuvable")
            return []
        data = http_get(_ITEM + tid).json()
    except Exception as e:  # noqa: BLE001
        log.warning("hn échec: %s", type(e).__name__)
        return []

    kws = _keywords(cfg)
    out: list[RawOffer] = []
    for child in (data.get("children") or [])[: sc.get("max_comments", 400)]:
        text = _strip_html(child.get("text", ""))
        if len(text) < 40:
            continue
        low = text.lower()
        if not any(k in low for k in kws):
            continue
        # Le format canonique HN est "Company | Role | Location | (REMOTE) | ...".
        head = text.split("\n", 1)[0][:220]
        parts = [p.strip() for p in head.split("|")]
        if len(parts) < 2:
            continue  # pas au format -> trop peu fiable à parser
        company = re.sub(r"https?://\S+", "", parts[0]).strip()[:80] or "HN"
        title = parts[1][:120]
        if not title or title.lower().startswith("http") or company.lower() == title.lower():
            continue
        # parts[1] doit ressembler à un intitulé de poste, pas à un lieu / une techno.
        if not re.search(r"(founder|associate|chief|operations|ops|sdr|bdr|sales|growth|"
                         r"business develop|gtm|generalist|consultant|manager|coordinator|"
                         r"trainer|analyst|revops)", title, re.I):
            continue
        location = " | ".join(parts[2:4])[:120]
        m = _URL_RX.search(text)
        url = m.group(0).rstrip(".,)") if m else f"https://news.ycombinator.com/item?id={child.get('id')}"
        out.append(RawOffer(
            title=title,
            company=company,
            description=text[:3000],
            url=url,
            location=location,
            published_at=child.get("created_at"),
            source="hn_whoishiring",
            external_id=str(child.get("id", "")),
        ))
    log.info("hn: %d offres", len(out))
    return out
