import email
from email.message import EmailMessage

import pytest

from sources import email_inbox


def _msg(sender: str, html: str) -> bytes:
    m = EmailMessage()
    m["From"] = sender
    m["Subject"] = "Nouvelles offres"
    m.set_content("version texte")
    m.add_alternative(html, subtype="html")
    return m.as_bytes()


LINKEDIN_HTML = """
<html><body>
<a href="https://www.linkedin.com/comm/jobs/view/chief-of-staff-3931001?trk=eml">Chief of Staff</a>
<a href="https://www.linkedin.com/comm/jobs/view/3931002?midToken=x">Founder Associate Intern</a>
<a href="https://www.linkedin.com/help">Aide</a>
</body></html>
"""

MALT_HTML = """
<html><body>
<a href="https://www.malt.fr/profile/xyz">mon profil</a>
<a href="https://www.malt.fr/project/mission-sdr-freelance-remote">Mission SDR freelance remote</a>
<a href="https://www.malt.fr/o/consultant-ia-junior-paris">Consultant IA junior</a>
<a href="https://www.malt.fr/">Voir l'offre</a>
</body></html>
"""


class FakeIMAP:
    instances = []

    def __init__(self, host):
        self.host = host
        self.msgs = FakeIMAP._MSGS
        self.seen = []
        FakeIMAP.instances.append(self)

    def login(self, u, p):
        return "OK", []

    def select(self, mailbox):
        return ("OK", []) if FakeIMAP._SELECT_OK else ("NO", [])

    def search(self, charset, *criteria):
        return "OK", [b" ".join(str(i).encode() for i in range(1, len(self.msgs) + 1))]

    def fetch(self, mid, spec):
        idx = int(mid) - 1
        return "OK", [(b"1 (RFC822 {n}", self.msgs[idx])]

    def store(self, mid, flags, value):
        self.seen.append(mid)
        return "OK", []

    def logout(self):
        return "OK", []


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    monkeypatch.setattr(email_inbox, "env",
                        lambda n, d=None: {"GMAIL_USER": "me@gmail.com",
                                           "GMAIL_APP_PASSWORD": "pw"}.get(n, d))
    monkeypatch.setattr(email_inbox.imaplib, "IMAP4_SSL", FakeIMAP)
    FakeIMAP.instances.clear()
    FakeIMAP._SELECT_OK = True


def _cfg(base, over):
    c = dict(base)
    c["sources"] = {**base["sources"], "email_inbox": {"enabled": True, "label": "Veille", **over}}
    return c


def test_linkedin_alert_parsed(cfg):
    FakeIMAP._MSGS = [_msg("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", LINKEDIN_HTML)]
    offers = email_inbox.fetch(_cfg(cfg, {}))
    urls = {o.url for o in offers}
    assert "https://www.linkedin.com/jobs/view/3931001" in urls
    assert "https://www.linkedin.com/jobs/view/3931002" in urls
    assert all("help" not in u for u in urls)
    assert FakeIMAP.instances[0].seen  # messages marqués lus


def test_unknown_sender_uses_generic_parser(cfg):
    FakeIMAP._MSGS = [_msg("Malt <hello@malt.com>", MALT_HTML)]
    offers = email_inbox.fetch(_cfg(cfg, {}))
    titles = {o.title for o in offers}
    assert "Mission SDR freelance remote" in titles
    assert "Consultant IA junior" in titles
    assert "mon profil" not in titles and "Voir l'offre" not in titles


def test_no_credentials_returns_empty(cfg, monkeypatch):
    monkeypatch.setattr(email_inbox, "env", lambda *a, **k: None)
    assert email_inbox.fetch(_cfg(cfg, {})) == []


def test_missing_label_returns_empty(cfg):
    FakeIMAP._SELECT_OK = False
    FakeIMAP._MSGS = []
    assert email_inbox.fetch(_cfg(cfg, {})) == []
