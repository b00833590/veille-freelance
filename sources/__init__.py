"""Registre des sources : nom -> fonction fetch(cfg) -> list[RawOffer]."""
from sources import (
    adzuna,
    email_inbox,
    france_travail,
    hn_whoishiring,
    jobicy,
    linkedin,
    remotive,
    themuse,
    wttj,
)

SOURCES = {
    "france_travail": france_travail.fetch,
    "adzuna": adzuna.fetch,
    "themuse": themuse.fetch,
    "remotive": remotive.fetch,
    "jobicy": jobicy.fetch,
    "hn_whoishiring": hn_whoishiring.fetch,
    "wttj": wttj.fetch,
    "linkedin": linkedin.fetch,
    "email_inbox": email_inbox.fetch,
}
