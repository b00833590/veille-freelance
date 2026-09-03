"""Socle commun aux sources : type RawOffer + client HTTP robuste."""
from __future__ import annotations

import logging
import random
import time
from dataclasses import asdict, dataclass, field

import httpx

log = logging.getLogger("veille.sources")

_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

_TIMEOUT = httpx.Timeout(20.0)
_RETRIES = 3


@dataclass
class RawOffer:
    title: str
    company: str = ""
    description: str = ""
    url: str = ""
    location: str = ""
    published_at: str | None = None
    source: str = ""
    external_id: str = ""
    salary_raw: str | None = None
    contract_type: str | None = None
    work_time: str | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def http_get(url: str, *, params=None, headers=None, client: httpx.Client | None = None,
             **kw) -> httpx.Response:
    h = {"User-Agent": random.choice(_UAS), "Accept": "application/json, text/html;q=0.9"}
    if headers:
        h.update(headers)
    last: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            if client is not None:
                resp = client.get(url, params=params, headers=h, timeout=_TIMEOUT, **kw)
            else:
                resp = httpx.get(url, params=params, headers=h, timeout=_TIMEOUT,
                                 follow_redirects=True, **kw)
            if resp.status_code in (429, 500, 502, 503, 999):
                raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
            return resp
        except (httpx.HTTPError, httpx.TransportError) as e:
            last = e
            if attempt < _RETRIES:
                time.sleep(1.5 * attempt + random.random())
    raise last  # type: ignore[misc]


def http_post(url: str, *, json=None, headers=None, **kw) -> httpx.Response:
    h = {"User-Agent": random.choice(_UAS), "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    last: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            resp = httpx.post(url, json=json, headers=h, timeout=_TIMEOUT, **kw)
            if resp.status_code in (429, 500, 502, 503, 999):
                raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
            return resp
        except (httpx.HTTPError, httpx.TransportError) as e:
            last = e
            if attempt < _RETRIES:
                time.sleep(1.5 * attempt + random.random())
    raise last  # type: ignore[misc]
