"""Ingestion des alertes emploi reçues par email (IMAP, label Gmail dédié).

L'utilisateur crée des alertes sur LinkedIn / Malt / WTTJ / Crème de la Crème ;
un filtre Gmail les range dans le label `Veille`. Ce module lit les non-lus,
extrait les liens d'offres, et les marque lus.
"""
from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import re
from email.message import Message

from selectolax.parser import HTMLParser

from settings import env
from sources.base import RawOffer

log = logging.getLogger("veille.sources.email")

_JOB_URL_RX = re.compile(
    r"/(jobs?/view|jobs?/|job/|offre|offres/|emploi/|careers?/|opportunit|o/|hiring"
    r"|project/|projet/|mission|freelance/|annonce)",
    re.IGNORECASE,
)
_TRACKING_HOSTS = ("click.", "email.", "e.", "track.", "links.", "comm.")


def _body_html(msg: Message) -> str:
    html, text = "", ""
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            decoded = payload.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        if ctype == "text/html":
            html += decoded
        else:
            text += decoded
    return html or f"<pre>{text}</pre>"


def _clean_url(href: str) -> str:
    href = re.sub(r"[?&](utm_[^&]+|trk|refId|midToken|lipi|eBP)=[^&]*", "", href)
    return href.rstrip("?&").strip()


def _looks_like_job(href: str) -> bool:
    return bool(href.startswith("http") and _JOB_URL_RX.search(href))


def _parse_generic(html: str, sender: str) -> list[RawOffer]:
    out: list[RawOffer] = []
    seen: set[str] = set()
    for a in HTMLParser(html).css("a"):
        href = _clean_url(a.attributes.get("href") or "")
        if not _looks_like_job(href):
            continue
        title = a.text(strip=True)
        if not title or len(title) < 3 or title.lower() in ("voir l'offre", "postuler",
                                                            "view job", "apply", "en savoir plus"):
            continue
        key = href.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(RawOffer(
            title=title[:160],
            company="",
            description="",
            url=href,
            location="",
            source="email_inbox",
            external_id="em_" + hashlib.sha1(key.encode()).hexdigest()[:16],
            extra={"via": sender},
        ))
    return out


def _parse_linkedin(html: str, sender: str) -> list[RawOffer]:
    out: list[RawOffer] = []
    seen: set[str] = set()
    tree = HTMLParser(html)
    for a in tree.css('a[href*="/jobs/view/"], a[href*="/comm/jobs/view/"]'):
        href = _clean_url(a.attributes.get("href") or "")
        m = re.search(r"/jobs/view/(?:[\w-]*-)?(\d{6,})", href)
        jid = m.group(1) if m else hashlib.sha1(href.encode()).hexdigest()[:12]
        if jid in seen:
            continue
        seen.add(jid)
        title = a.text(strip=True)
        if not title or len(title) < 3:
            continue
        out.append(RawOffer(
            title=title[:160], company="", description="",
            url=f"https://www.linkedin.com/jobs/view/{jid}" if m else href,
            location="", source="email_inbox", external_id=f"li_{jid}",
            extra={"via": "linkedin-alert"},
        ))
    return out or _parse_generic(html, sender)


_PARSERS = [
    ("linkedin.com", _parse_linkedin),
]


def _dispatch(sender: str, html: str) -> list[RawOffer]:
    low = sender.lower()
    for needle, parser in _PARSERS:
        if needle in low:
            return parser(html, sender)
    return _parse_generic(html, sender)


def fetch(cfg: dict) -> list[RawOffer]:
    sc = cfg["sources"]["email_inbox"]
    if not sc.get("enabled", True):
        return []
    user, pwd = env("GMAIL_USER"), env("GMAIL_APP_PASSWORD")
    if not user or not pwd:
        log.info("email_inbox désactivée (GMAIL_USER/APP_PASSWORD manquants)")
        return []

    host = sc.get("imap_host", "imap.gmail.com")
    label = sc.get("label", "Veille")
    out: list[RawOffer] = []
    try:
        M = imaplib.IMAP4_SSL(host)
        M.login(user, pwd)
        typ, _ = M.select(f'"{label}"')
        if typ != "OK":
            log.warning("email_inbox: label '%s' introuvable", label)
            M.logout()
            return []
        typ, data = M.search(None, "UNSEEN")
        ids = data[0].split()[: sc.get("max_messages", 60)]
        for mid in ids:
            typ, msg_data = M.fetch(mid, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            sender = str(msg.get("From", ""))
            offers = _dispatch(sender, _body_html(msg))
            out.extend(offers)
            M.store(mid, "+FLAGS", "\\Seen")
        M.logout()
    except Exception as e:  # noqa: BLE001
        log.warning("email_inbox échec: %s", type(e).__name__)
        return out

    # dédup interne
    uniq: dict[str, RawOffer] = {}
    for o in out:
        uniq.setdefault(o.url.split("?")[0], o)
    log.info("email_inbox: %d offres", len(uniq))
    return list(uniq.values())
