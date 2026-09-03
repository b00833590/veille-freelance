"""Point d'entrée CLI du système de veille.

    python main.py init-db
    python main.py scan [--source NAME ...]
    python main.py digest
    python main.py report
    python main.py recompute
    python main.py ingest-feedback --issue N --title "..." --body "..." --author "..."
"""
from __future__ import annotations

import argparse
import sys

from settings import db_path, load_config
from store import db


def _connect():
    conn = db.connect(db_path())
    db.init_db(conn)
    return conn


def cmd_init_db(_args) -> int:
    import os
    os.makedirs(os.path.dirname(db_path()) or ".", exist_ok=True)
    conn = db.connect(db_path())
    db.init_db(conn)
    print(f"Base initialisée : {db_path()}")
    return 0


def cmd_scan(args) -> int:
    from notify import alert
    from pipeline.run import scan
    from report import build_html
    conn = _connect()
    cfg = load_config()
    stats = scan(conn, cfg, source_names=args.source or None)
    alert.maybe_send(conn, cfg, stats.get("new_priority1_ids", []))
    build_html.build(conn, cfg)
    print(stats)
    return 0


def cmd_digest(_args) -> int:
    from notify import email_digest
    conn = _connect()
    email_digest.send(conn, load_config())
    return 0


def cmd_report(_args) -> int:
    from report import build_html
    conn = _connect()
    build_html.build(conn, load_config())
    print("Dashboard régénéré dans docs/")
    return 0


def cmd_recompute(_args) -> int:
    from pipeline.run import recompute
    conn = _connect()
    print(recompute(conn, load_config()))
    return 0


def cmd_ingest_feedback(args) -> int:
    from feedback import ingest
    conn = _connect()
    msg = ingest.handle(
        conn, load_config(),
        title=args.title, body=args.body or "", author=args.author or "",
    )
    print(msg)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Système de veille freelance / temps partiel")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db").set_defaults(func=cmd_init_db)

    sp = sub.add_parser("scan")
    sp.add_argument("--source", action="append", help="limiter à cette/ces source(s)")
    sp.set_defaults(func=cmd_scan)

    sub.add_parser("digest").set_defaults(func=cmd_digest)
    sub.add_parser("report").set_defaults(func=cmd_report)
    sub.add_parser("recompute").set_defaults(func=cmd_recompute)

    fp = sub.add_parser("ingest-feedback")
    fp.add_argument("--issue", type=int)
    fp.add_argument("--title", required=True)
    fp.add_argument("--body")
    fp.add_argument("--author")
    fp.set_defaults(func=cmd_ingest_feedback)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
