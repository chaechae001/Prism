"""RSS parsing and publisher article identity, separate from body acquisition."""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class Source:
    key: str
    publisher: str
    feed_url: str
    hosts: tuple[str, ...]
    category: str = "economy"


SOURCES = {
    "khan": Source("khan", "경향신문", "https://www.khan.co.kr/rss/rssdata/economy_news.xml", ("www.khan.co.kr", "khan.co.kr")),
    "sbs": Source("sbs", "SBS", "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=02&plink=RSSREADER", ("news.sbs.co.kr",)),
    "mk": Source("mk", "매일경제", "https://www.mk.co.kr/rss/30100041/", ("www.mk.co.kr", "mk.co.kr")),
}


def checked_url(url: str) -> str:
    """Validate URL syntax. Domain and DNS checks are enforced before HTTP."""
    value = url.strip()
    if any(ord(char) < 33 for char in value) or "\\" in value:
        raise ValueError("invalid_url")
    try:
        parts = urlsplit(value)
        if (parts.scheme not in {"http", "https"} or not parts.hostname or
                parts.username is not None or parts.password is not None or
                parts.port not in {None, 80 if parts.scheme == "http" else 443}):
            raise ValueError("invalid_url")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid_url") from exc
    return value


def canonical_url(url: str) -> str:
    """Match the existing clustering RSS adapter's URL-based ID convention."""
    parts = urlsplit(checked_url(url))
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"plink", "fbclid", "gclid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(sorted(query)), ""))


def source_for_url(url: str) -> Source | None:
    try:
        host = urlsplit(checked_url(url)).hostname
    except ValueError:
        return None
    return next((source for source in SOURCES.values() if host in source.hosts), None)


def article_identity(url: str) -> tuple[str, str] | None:
    source = source_for_url(url)
    if source is None:
        return None
    parts = urlsplit(url)
    if source.key == "sbs" and parts.path == "/news/endPage.do":
        ids = [value for key, value in parse_qsl(parts.query) if key == "news_id"]
        if len(ids) == 1 and re.fullmatch(r"N\d{7,15}", ids[0]):
            return source.key, ids[0]
    if source.key == "khan":
        match = re.search(r"/article/(\d{12,20})/?$", parts.path)
        if match:
            return source.key, match.group(1)
    if source.key == "mk":
        match = re.fullmatch(r"/news/[^/]+/(\d{5,15})/?", parts.path)
        if match:
            return source.key, match.group(1)
    return None


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.blocked = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "noscript"}:
            self.blocked.append(tag)
        if not self.blocked and tag in {"p", "div", "br", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.blocked and tag == self.blocked[-1]:
            self.blocked.pop()
        if not self.blocked and tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def plain_text(value: str) -> str:
    parser = _PlainText()
    parser.feed(value)
    return " ".join(unicodedata.normalize("NFC", unescape("".join(parser.parts))).split())


def normalize_date(raw: str) -> str | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            value = parsedate_to_datetime(raw)
        except (ValueError, TypeError, OverflowError):
            return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    try:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, ValueError):
        return None


def parse_feed(raw: bytes, source: Source) -> list[dict]:
    if len(raw) > 5_000_000 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("unsafe_or_oversized_rss")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("invalid_rss_xml") from exc
    channel = root.find("channel") if root.tag == "rss" else None
    if channel is None:
        raise ValueError("rss_2_channel_required")
    items = []
    for position, node in enumerate(channel.findall("item"), 1):
        guid_node = node.find("guid")
        guid = (node.findtext("guid") or "").strip()
        link = (node.findtext("link") or "").strip()
        if not link and guid_node is not None and guid_node.get("isPermaLink", "true").lower() != "false":
            link = guid
        title = plain_text(node.findtext("title") or "")
        date = normalize_date(node.findtext("pubDate") or node.findtext("{http://purl.org/dc/elements/1.1/}date") or "")
        item = {
            "rss_position": position, "source_id": f"{source.key}-{source.category}",
            "publisher": source.publisher, "category": source.category,
            "rss_guid": guid or None, "rss_link": (node.findtext("link") or "").strip() or None,
            "rss_description": plain_text(node.findtext("description") or ""),
            "rss_content": plain_text(node.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""),
            "title": title, "published_at": date, "url": None,
            "article_id": None, "publisher_article_id": None, "issue": None,
            "warnings": [] if date else ["missing_or_invalid_publication_time"],
        }
        identity = article_identity(link) if link else None
        if not link:
            item["issue"] = "missing_article_url"
        elif identity is None or identity[0] != source.key:
            item["issue"] = "unsupported_article_url"
        else:
            item["url"] = canonical_url(link)
            item["publisher_article_id"] = identity[1]
            item["article_id"] = "article-" + sha256(item["url"].encode()).hexdigest()[:24]
            guid_identity = article_identity(guid) if guid else None
            if guid_identity is not None and guid_identity != identity:
                item["issue"] = "rss_id_mismatch"
            elif not title:
                item["issue"] = "missing_title"
        items.append(item)
    return items
