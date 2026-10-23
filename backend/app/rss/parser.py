"""RSS 2.0 XML을 내부 저장 값과 공통 JSON으로 변환합니다.

네트워크 요청과 DB 연결은 하지 않습니다. HTML과 미디어는 내부 값으로만
보존하며, 화면에 넣기 전 별도의 처리와 이용 범위 확인이 필요합니다.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import re
from typing import Mapping
from urllib.parse import unquote_plus, urlsplit, urlunsplit
from xml.etree import ElementTree as ET


RIGHT_KEYS = ("collect", "store", "summarize", "publish_summary", "display_image")
CATEGORIES = {"politics", "economy", "society", "technology"}
DC = "{http://purl.org/dc/elements/1.1/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
MEDIA = "{http://search.yahoo.com/mrss/}"
MAX_XML_BYTES = 5 * 1024 * 1024


class RSSParseError(ValueError):
    """XML 문서 전체를 해석할 수 없어 항목 처리를 시작할 수 없는 경우."""


@dataclass(frozen=True)
class FeedConfig:
    feed_id: str
    publisher_id: str
    publisher_name: str
    default_category: str
    is_demo: bool
    rights: Mapping[str, str] = field(
        default_factory=lambda: dict.fromkeys(RIGHT_KEYS, "unknown")
    )

    def __post_init__(self):
        for value in (self.feed_id, self.publisher_id, self.publisher_name):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("피드와 언론사 식별 정보는 비어 있을 수 없습니다.")
        if self.default_category not in CATEGORIES:
            raise ValueError("지원하지 않는 기본 카테고리입니다.")
        if type(self.is_demo) is not bool:
            raise ValueError("is_demo에는 bool 값을 명시해야 합니다.")
        if set(self.rights) != set(RIGHT_KEYS) or any(
            value not in ("allowed", "unknown", "denied")
            for value in self.rights.values()
        ):
            raise ValueError("rights에는 다섯 권한의 유효한 상태가 필요합니다.")
        # 호출자가 원래 사전을 변경해도 피드 설정에 소급 반영하지 않습니다.
        object.__setattr__(self, "rights", dict(self.rights))


@dataclass
class ParsedItem:
    feed: FeedConfig
    storage: dict

    def to_record(self) -> dict | None:
        """공통 규격의 20개 키만 반환합니다. 오류 항목은 내부에만 남깁니다."""
        data = self.storage
        if data["parse_status"] == "error":
            return None
        keys = (
            "id", "feed_id", "item_key", "source_item_id", "original_url",
            "canonical_url", "title", "category", "author", "source_category",
            "rss_description", "published_at", "collected_at", "parse_status",
            "body_status", "is_demo",
        )
        return {
            "schema_version": "1.0",
            **{key: data[key] for key in keys},
            "publisher_id": self.feed.publisher_id,
            "publisher_name": self.feed.publisher_name,
            "rights": dict(data["rights_snapshot"]),
        }


def canonicalize_url(value: str) -> str:
    """추적용 UTM만 제거하고 기사 식별에 쓰이는 쿼리는 유지합니다."""
    if not isinstance(value, str) or re.search(r"[\s\x00-\x1f\x7f]", value):
        raise ValueError("URL에 공백 또는 제어 문자가 있습니다.")
    try:
        parts = urlsplit(value)
        if not value.startswith(("http://", "https://")) or not parts.hostname:
            raise ValueError("HTTP(S) 절대 URL이 필요합니다.")
        if parts.username is not None or parts.password is not None:
            raise ValueError("인증 정보가 들어 있는 URL은 허용하지 않습니다.")
        port = parts.port
    except ValueError as exc:
        raise ValueError("올바르지 않은 기사 URL입니다.") from exc
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    scheme = parts.scheme.lower()
    if port is not None and (scheme, port) not in (("http", 80), ("https", 443)):
        host += f":{port}"
    # 쿼리를 재인코딩하면 서명이나 기사 식별 값이 바뀔 수 있어 원래 조각을 유지합니다.
    query = "&".join(
        pair for pair in parts.query.split("&")
        if pair and not unquote_plus(pair.split("=", 1)[0]).lower().startswith("utm_")
    )
    return urlunsplit((scheme, host, parts.path or "/", query, ""))


def _text(item: ET.Element, name: str) -> str | None:
    node = item.find(name)
    if node is None:
        return None
    return "".join(node.itertext()).strip() or None


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("시각에는 시간대가 있어야 합니다.")
    return value.astimezone(timezone.utc).isoformat()


def _published(raw: str | None) -> tuple[str | None, str | None]:
    if not raw:
        return None, "missing_published_at"
    try:
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            value = parsedate_to_datetime(raw)
        if value.tzinfo is None or value.utcoffset() is None:
            return None, "missing_published_timezone"
        return _utc_iso(value), None
    except (ValueError, TypeError, OverflowError):
        return None, "invalid_published_at"


def _parse_item(item: ET.Element, feed: FeedConfig, collected_at: str) -> ParsedItem:
    raw_xml = ET.tostring(item, encoding="unicode")
    title = _text(item, "title")
    original_url = _text(item, "link")
    issues = []
    if title is None:
        issues.append("missing_title")
    canonical_url = None
    try:
        canonical_url = canonicalize_url(original_url) if original_url else None
        if canonical_url is None:
            issues.append("missing_url")
    except ValueError:
        issues.append("invalid_url")

    guid, number = _text(item, "guid"), _text(item, "no")
    source_item_id = guid or number
    # GUID와 no가 같은 문자열이어도 서로 다른 식별 체계로 구분합니다.
    if guid:
        item_key = "guid-v1:" + guid
    elif number:
        item_key = "no-v1:" + number
    elif canonical_url:
        item_key = "url-v1:" + canonical_url
    else:
        # 필수 값 오류도 재수신 시 같은 키로 보존합니다. 시각은 키에 넣지 않습니다.
        item_key = "invalid-v1:" + sha256(raw_xml.encode()).hexdigest()
    # 피드가 다르면 같은 기사라도 각각의 수신 이력을 갖습니다.
    record_id = "rss-v1-" + sha256(
        (feed.feed_id + "\0" + item_key).encode()
    ).hexdigest()

    raw_date = _text(item, "pubDate") or _text(item, DC + "date")
    published_at, date_issue = _published(raw_date)
    if date_issue:
        issues.append(date_issue)
    description = _text(item, "description")
    content = _text(item, CONTENT + "encoded")
    media = []
    for node in item.iter():
        if node.tag in (MEDIA + "content", MEDIA + "thumbnail", "enclosure"):
            media.append({"kind": node.tag, **dict(node.attrib)})
    # 내용 유무와 이용 허용 여부는 서로 다릅니다. unknown을 allowed로 바꾸지 않습니다.
    body_status = (
        "blocked" if "denied" in (feed.rights["collect"], feed.rights["store"])
        else "content_available" if content else "rss_excerpt" if description
        else "not_provided"
    )
    required_error = title is None or canonical_url is None
    return ParsedItem(feed, {
        "id": record_id,
        "feed_id": feed.feed_id,
        "item_key": item_key,
        "source_item_id": source_item_id,
        "original_url": original_url,
        "canonical_url": canonical_url,
        "title": title,
        "author": _text(item, "author") or _text(item, DC + "creator"),
        "source_category": _text(item, "category"),
        # 소스의 '산업/지역정치' 등은 보존하고, 합의된 네 카테고리는 설정에서 받습니다.
        "category": feed.default_category,
        "rss_description": description,
        "content_html": content,
        "media": media,
        "raw_item_xml": raw_xml,
        "source_published_raw": raw_date,
        "published_at": published_at,
        "collected_at": collected_at,
        "last_seen_at": collected_at,
        "parse_status": "error" if required_error else "partial" if issues else "parsed",
        "parse_issues": issues,
        "body_status": body_status,
        "rights_snapshot": dict(feed.rights),
        "is_demo": feed.is_demo,
    })


def parse_rss(
    xml: str | bytes, *, feed: FeedConfig, collected_at: datetime | None = None
) -> list[ParsedItem]:
    """UTF-8 RSS 2.0을 변환합니다. 문서 오류는 빈 목록 대신 예외로 알립니다.

    항목 내부 오류는 storage에 보존합니다. 이 함수는 저장 권한을 부여하거나
    실제 저장을 수행하지 않으므로 수집/저장 계층에서 별도로 허용 여부를 검사합니다.
    """
    if not isinstance(xml, (str, bytes)):
        raise TypeError("XML은 str 또는 bytes여야 합니다.")
    if len(xml) > MAX_XML_BYTES:
        raise RSSParseError("XML 크기 제한은 5 MiB입니다.")
    try:
        source = xml.decode("utf-8-sig") if isinstance(xml, bytes) else xml
        if len(source.encode("utf-8")) > MAX_XML_BYTES:
            raise RSSParseError("XML 크기 제한은 5 MiB입니다.")
        # 이번 구현은 UTF-8 RSS만 받습니다. 외부 엔티티와 DTD는 처리하지 않습니다.
        declaration = re.match(r"\ufeff?\s*<\?xml\s+([^?]*)\?>", source)
        if declaration:
            encoding = re.search(r"encoding\s*=\s*['\"]([^'\"]+)['\"]", declaration[1])
            if encoding and encoding[1].lower() not in ("utf-8", "utf8"):
                raise RSSParseError("이번 파서는 UTF-8 XML만 지원합니다.")
        if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", source, re.IGNORECASE):
            raise RSSParseError("DTD 또는 엔티티 선언은 지원하지 않습니다.")
        root = ET.fromstring(source)
    except (UnicodeDecodeError, ET.ParseError, RecursionError) as exc:
        raise RSSParseError("RSS XML을 읽을 수 없습니다.") from exc
    if root.tag != "rss" or root.get("version") != "2.0":
        raise RSSParseError("이번 파서는 RSS 2.0만 지원합니다.")
    channel = root.find("channel")
    if channel is None:
        raise RSSParseError("RSS channel이 없습니다.")
    timestamp = _utc_iso(collected_at if collected_at is not None else datetime.now(timezone.utc))
    return [_parse_item(item, feed, timestamp) for item in channel.findall("item")]
