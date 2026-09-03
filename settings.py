"""Chargement de config.yaml + accès aux secrets via variables d'environnement."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.yaml"


@lru_cache(maxsize=4)
def load_config(path: str | None = None) -> dict:
    p = Path(path) if path else CONFIG_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    return val if val not in ("", None) else default


def db_path() -> str:
    return env("VEILLE_DB", str(ROOT / "data" / "veille.db"))
