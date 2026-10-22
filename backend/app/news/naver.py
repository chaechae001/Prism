"""Naver Search finds metadata, never article full text. No arbitrary URL fetching."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import os
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from uuid import NAMESPACE_URL, uuid5

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..rss_preview import plain_text
from .models import NewsRecord, Publisher


class NaverItem(BaseModel):
    # Provider may add fields. Internal contracts remain strict.
    model_config = ConfigDict(extra="ignore")
    title: str
    originallink: str = ""
    link: str
    description: str = ""
    pubDate: str = ""


class NaverPage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    lastBuildDate: str
    total: int = Field(ge=0)
    start: int = Field(ge=1)
    display: int = Field(ge=0)
    items: list[NaverItem]


class NaverError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def canonical_url(value: str) -> str:
    u = urlsplit(value.strip())
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("Invalid article URL")
    # Preserve meaningful article IDs, ports, paths and remaining query parameters.
    query = [
        (k, v)
        for k, v in parse_qsl(u.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")
    ]
    return urlunsplit(
        (u.scheme.lower(), u.netloc.lower(), u.path or "/", urlencode(query), "")
    )


def normalize(
    item: NaverItem,
    category: str,
    publishers: list[Publisher],
    *,
    collected_at=None,
    is_demo=False,
) -> NewsRecord:
    original = item.originallink.strip() or item.link
    canonical = canonical_url(original)
    host = urlsplit(canonical).hostname
    matches = [
        (len(domain), p)
        for p in publishers
        for domain in p.domains
        if host == domain.lower() or host.endswith("." + domain.lower())
    ]
    publisher = max(matches, key=lambda x: x[0])[1] if matches else None
    try:
        published = parsedate_to_datetime(item.pubDate)
        if published.tzinfo is None:
            published = None
    except (ValueError, TypeError, OverflowError):
        published = None
    return NewsRecord(
        id=uuid5(NAMESPACE_URL, canonical),
        provider="naver_search",
        provider_url=item.link,
        original_url=original,
        canonical_url=canonical,
        title=plain_text(item.title),
        snippet=plain_text(item.description),
        publisher=publisher,
        category=category,
        provider_published_at=published,
        collected_at=collected_at or datetime.now(timezone.utc),
        is_demo=is_demo,
    )


class NaverClient:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client

    def search(self, query: str, display=100, start=1, sort="date") -> NaverPage:
        if (
            not query.strip()
            or len(query) > 100
            or not 1 <= display <= 100
            or not 1 <= start <= 1000
            or sort not in ("sim", "date")
        ):
            raise ValueError("Invalid Naver search parameters")
        client_id, secret = (
            os.getenv("NAVER_CLIENT_ID"),
            os.getenv("NAVER_CLIENT_SECRET"),
        )
        if not client_id or not secret:
            raise NaverError("NAVER_CREDENTIALS_MISSING")
        headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": secret}

        def send(client):
            try:
                response = client.get(
                    "https://openapi.naver.com/v1/search/news.json",
                    params={
                        "query": query,
                        "display": display,
                        "start": start,
                        "sort": sort,
                    },
                    headers=headers,
                    timeout=15,
                    follow_redirects=False,
                )
            except httpx.RequestError:
                raise NaverError("NAVER_NETWORK_ERROR") from None
            if response.status_code != 200:
                code = (
                    "NAVER_RATE_LIMITED"
                    if response.status_code == 429
                    else "NAVER_AUTH_ERROR"
                    if response.status_code in (401, 403)
                    else "NAVER_UPSTREAM_ERROR"
                )
                raise NaverError(code)
            try:
                return NaverPage.model_validate(response.json())
            except (ValueError, TypeError):
                raise NaverError("NAVER_INVALID_RESPONSE") from None

        if self.client:
            return send(self.client)
        with httpx.Client() as client:
            return send(client)
