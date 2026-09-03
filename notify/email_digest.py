"""Digest quotidien : 🔥 priorité 1, 🟢 priorité 2, 🧭 exploration."""
from __future__ import annotations

import logging
import math
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from notify.formatting import offer_card
from notify.mailer import send_mail
from pipeline.preferences import explain_match
from store import db
from store.db import now_iso

log = logging.getLogger("veille.digest")

_EPOCH = "1970-01-01T00:00:00+00:00"
_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).with_name("templates"))),
    autoescape=select_autoescape(["html", "j2"]),
)


def _dashboard_url(cfg: dict) -> str:
    gh = cfg["github"]
    return f"https://{gh['owner']}.github.io/{gh['repo']}/"


def _select(conn, cfg: dict):
    since = db.get_state(conn, "last_digest_at", _EPOCH)
    max_items = cfg["digest"]["max_items"]
    explore_ratio = cfg["digest"]["explore_ratio"]
    explore_min = cfg["digest"]["explore_min_raw_score"]
    n_explore = math.floor(max_items * explore_ratio)
    n_main = max_items - n_explore

    main = conn.execute(
        "SELECT * FROM offers WHERE archived = 0 AND status = 'new' "
        "AND priority IN (1, 2) AND discovered_at > ? "
        "ORDER BY priority ASC, score DESC LIMIT ?",
        (since, n_main),
    ).fetchall()
    main_ids = {r["id"] for r in main}

    explore = conn.execute(
        "SELECT * FROM offers WHERE archived = 0 AND status = 'new' "
        "AND discovered_at > ? AND score >= ? AND id NOT IN (%s) "
        "AND (category = 'UNKNOWN' OR priority = 3) "
        "ORDER BY score DESC LIMIT ?" % (",".join("?" * len(main_ids)) or "''"),
        (since, explore_min, *main_ids, n_explore),
    ).fetchall() if n_explore else []

    return main, explore, since


def build(conn, cfg: dict) -> tuple[str, str, int]:
    main, explore, _ = _select(conn, cfg)
    total = len(main) + len(explore)

    def cards(rows):
        out = []
        for r in rows:
            o = db.get_offer(conn, r["id"])
            out.append(offer_card(o, cfg, match_notes=explain_match(conn, o)))
        return out

    p1 = [c for c in cards(main) if c["priority"] == 1]
    p2 = [c for c in cards(main) if c["priority"] == 2]
    ex = cards(explore)

    if total == 0:
        subject = "🔎 Veille — rien de neuf aujourd'hui"
        html = _env.get_template("digest.html.j2").render(
            title=subject, subtitle="Aucune nouvelle offre au-dessus du seuil.",
            sections=[], dashboard_url=_dashboard_url(cfg))
        return subject, html, 0

    subject = f"🔎 Veille — {len(p1)} 🔥 · {len(p2)} 🟢" + (f" · {len(ex)} 🧭" if ex else "")
    html = _env.get_template("digest.html.j2").render(
        title="Tes nouvelles opportunités",
        subtitle=f"{total} offre(s) depuis le dernier digest.",
        sections=[
            {"label": "🔥 Priorité 1 — à candidater rapidement", "cards": p1},
            {"label": "🟢 Priorité 2 — à regarder", "cards": p2},
            {"label": "🧭 Exploration — catégories nouvelles", "cards": ex},
        ],
        dashboard_url=_dashboard_url(cfg),
    )
    return subject, html, total


def send(conn, cfg: dict) -> int:
    subject, html, total = build(conn, cfg)
    send_mail(subject, html)
    db.set_state(conn, "last_digest_at", now_iso())
    log.info("digest: %d offres", total)
    return total
