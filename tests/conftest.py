import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import db  # noqa: E402


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture
def cfg():
    from settings import load_config
    return load_config()


def make_offer(**over):
    """Offre minimale valide pour les tests."""
    base = {
        "id": "fp-test-1",
        "fingerprint": "fp-test-1",
        "title": "AI Operations Intern",
        "company": "Startup X",
        "company_norm": "startup x",
        "description": "Build AI workflows, business development, no coding required.",
        "url": "https://example.com/jobs/1",
        "url_canonical": "https://example.com/jobs/1",
        "sources": [{"source": "themuse", "url": "https://example.com/jobs/1"}],
        "location": "Paris",
        "remote": "hybrid",
        "work_time": "internship",
    }
    base.update(over)
    return base
