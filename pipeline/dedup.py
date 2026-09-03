"""Normalisation et déduplication des offres."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse, urlunparse

from rapidfuzz import fuzz

from store.db import now_iso

_LEGAL_SUFFIXES = {
    "sas", "sasu", "sarl", "sa", "eurl", "inc", "llc", "ltd", "limited", "gmbh",
    "ag", "bv", "srl", "spa", "plc", "co", "corp", "group", "groupe", "holding",
}
_STOPWORDS = {"the", "a", "an", "le", "la", "les", "de", "du", "des", "and", "et"}
_TRACKING_PREFIXES = ("utm_", "gh_", "ref", "source", "src", "trk", "trackingid")

_FUZZY_THRESHOLD = 90


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _clean(s: str) -> str:
    s = _strip_accents((s or "").lower())
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_company(name: str) -> str:
    # "S.A.R.L." -> "SARL" avant nettoyage, pour attraper les formes pointées.
    name = re.sub(r"\.", "", name or "")
    tokens = [t for t in _clean(name).split() if t not in _LEGAL_SUFFIXES]
    return " ".join(tokens).strip()


def normalize_title(title: str) -> str:
    # Retire mentions de genre et bruit courant.
    t = _clean(title)
    t = re.sub(r"\b(h ?f|f ?h|m ?f|w ?m|m ?w|x ?f)\b", " ", t)
    t = re.sub(r"\b(cdi|cdd|stage|freelance|internship|intern|alternance|apprenticeship)\b", " ", t)
    tokens = [w for w in t.split() if w not in _STOPWORDS]
    return re.sub(r"\s+", " ", " ".join(tokens)).strip()


def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip()
    scheme = (p.scheme or "https").lower()
    netloc = p.netloc.lower()
    query_parts = [
        kv for kv in p.query.split("&")
        if kv and not kv.lower().startswith(_TRACKING_PREFIXES)
    ]
    query = "&".join(query_parts)
    path = p.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", query, ""))


def fingerprint(company: str, title: str, city: str) -> str:
    key = "|".join((
        normalize_company(company),
        normalize_title(title),
        _clean((city or "").split(",")[0]),
    ))
    return "fp_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def _cities_compatible(a: str, b: str) -> bool:
    a, b = _clean((a or "").split(",")[0]), _clean((b or "").split(",")[0])
    if not a or not b:
        return True
    return a == b or a in b or b in a


def find_duplicate(conn, offer: dict) -> str | None:
    """Retourne l'id d'une offre existante équivalente, sinon None."""
    cu = offer.get("url_canonical") or canonical_url(offer.get("url", ""))
    if cu:
        row = conn.execute(
            "SELECT id FROM offers WHERE url_canonical = ? LIMIT 1", (cu,)
        ).fetchone()
        if row:
            return row["id"]

    fp = offer.get("fingerprint") or fingerprint(
        offer.get("company", ""), offer.get("title", ""), offer.get("location", "")
    )
    row = conn.execute("SELECT id FROM offers WHERE fingerprint = ? LIMIT 1", (fp,)).fetchone()
    if row:
        return row["id"]

    cn = offer.get("company_norm") or normalize_company(offer.get("company", ""))
    if not cn:
        return None
    tn = normalize_title(offer.get("title", ""))
    for row in conn.execute(
        "SELECT id, title, location FROM offers WHERE company_norm = ?", (cn,)
    ):
        if fuzz.token_sort_ratio(tn, normalize_title(row["title"])) >= _FUZZY_THRESHOLD \
                and _cities_compatible(offer.get("location", ""), row["location"] or ""):
            return row["id"]
    return None


def merge_sources(existing: dict, new: dict) -> dict:
    """Fusionne `new` dans `existing` : accumule les sources, comble les vides."""
    merged = dict(existing)
    seen = {s.get("source") for s in existing.get("sources", []) if isinstance(s, dict)}
    for s in new.get("sources", []):
        if isinstance(s, dict) and s.get("source") not in seen:
            merged.setdefault("sources", [])
            merged["sources"] = list(merged["sources"]) + [{**s, "seen_at": s.get("seen_at") or now_iso()}]
            seen.add(s.get("source"))

    for field in ("salary_raw", "salary_min", "salary_max", "published_at",
                  "contract_type", "location", "remote", "work_time"):
        if not merged.get(field) and new.get(field):
            merged[field] = new[field]
    if len(new.get("description") or "") > len(merged.get("description") or ""):
        merged["description"] = new["description"]

    merged["last_checked_at"] = now_iso()
    return merged
