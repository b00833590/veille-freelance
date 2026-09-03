"""Alerte immédiate quand une offre 🔥 (priorité 1) apparaît hors digest."""
from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from notify.formatting import offer_card
from notify.mailer import send_mail
from store import db

log = logging.getLogger("veille.alert")

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).with_name("templates"))),
    autoescape=select_autoescape(["html", "j2"]),
)


def _dashboard_url(cfg: dict) -> str:
    gh = cfg["github"]
    return f"https://{gh['owner']}.github.io/{gh['repo']}/"


def maybe_send(conn, cfg: dict, new_offer_ids: list[str]) -> int:
    to_alert = []
    for oid in new_offer_ids:
        if db.get_state(conn, f"alerted:{oid}"):
            continue
        o = db.get_offer(conn, oid)
        if o and o.get("priority") == 1 and o.get("status") == "new":
            to_alert.append(o)

    if not to_alert:
        return 0

    cards = [offer_card(o, cfg) for o in to_alert]
    subject = f"🔥 {len(cards)} nouvelle(s) opportunité(s) prioritaire(s)"
    html = _env.get_template("digest.html.j2").render(
        title=subject, subtitle="Détectées lors du dernier scan.",
        sections=[{"label": "🔥 Priorité 1", "cards": cards}],
        dashboard_url=_dashboard_url(cfg),
    )
    if send_mail(subject, html):
        for o in to_alert:
            db.set_state(conn, f"alerted:{o['id']}", "1")
    log.info("alerte: %d offres", len(cards))
    return len(cards)
