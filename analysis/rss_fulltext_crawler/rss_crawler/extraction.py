"""Extract only a verified article body, never an RSS/search excerpt fallback."""

from html.parser import HTMLParser
from hashlib import sha256
import json
import re
import unicodedata
from urllib.parse import urljoin

from .parsing import Source, article_identity, plain_text


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
SKIP_TAGS = {"script", "style", "noscript", "iframe", "nav", "aside", "footer", "button"}
SKIP_CLASSES = {"ad", "ads", "advertisement", "related_news", "copyright", "reporter_area", "news_banner"}
ARTICLE_TYPES = {"Article", "NewsArticle", "ReportageNewsArticle", "AnalysisNewsArticle", "OpinionNewsArticle", "Report"}


def _text(parts: list[str]) -> str:
    lines = [" ".join(line.split()) for line in unicodedata.normalize("NFC", "".join(parts)).splitlines()]
    return "\n".join(line for line in lines if line).strip()


class _Document(HTMLParser):
    def __init__(self, source: Source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.urls = []
        self.title = ""
        self.published_at_raw = None
        self.stack = []
        self.containers = []
        self.json_scripts = []
        self.script = None

    def _selector(self, attrs):
        classes = set(attrs.get("class", "").split())
        identifier = attrs.get("id", "")
        if self.source.key == "sbs" and "text_area" in classes:
            return "text_area"
        if self.source.key == "khan":
            if identifier in {"articleBody", "articleBodyText"}:
                return identifier
            if "art_body" in classes:
                return "art_body"
        if self.source.key == "mk" and "news_cnt_detail_wrap" in classes:
            return "news_cnt_detail_wrap"
        return None

    def _append(self, value):
        if self.stack and not self.stack[-1][1]:
            for container in self.containers:
                if container["active"]:
                    container["parts"].append(value)

    def handle_starttag(self, tag, attrs):
        attributes = {key: value or "" for key, value in attrs}
        if tag == "link" and "canonical" in attributes.get("rel", "").lower().split() and attributes.get("href"):
            self.urls.append(("canonical", attributes["href"]))
        if tag == "meta":
            key = (attributes.get("property") or attributes.get("name", "")).lower()
            if key == "og:url" and attributes.get("content"):
                self.urls.append(("og:url", attributes["content"]))
            elif key == "og:title":
                self.title = plain_text(attributes.get("content", ""))
            elif key == "article:published_time":
                self.published_at_raw = attributes.get("content")
        if tag == "script" and attributes.get("type", "").lower().split(";")[0].strip() == "application/ld+json":
            self.script = []
        if tag == "br":
            self._append("\n")
        if tag in VOID_TAGS:
            return
        blocked = bool(self.stack and self.stack[-1][1]) or tag in SKIP_TAGS or bool(SKIP_CLASSES & set(attributes.get("class", "").split()))
        self.stack.append((tag, blocked))
        selector = self._selector(attributes)
        if selector and not blocked:
            self.containers.append({"selector": selector, "depth": len(self.stack), "parts": [], "active": True})
        if tag in {"p", "div", "li", "h2", "h3", "blockquote"}:
            self._append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            self.json_scripts.append("".join(self.script))
            self.script = None
        match = next((index for index in range(len(self.stack) - 1, -1, -1) if self.stack[index][0] == tag), None)
        if match is None:
            return
        if tag in {"p", "div", "li", "h2", "h3", "blockquote"}:
            self._append("\n")
        for container in self.containers:
            if container["active"] and container["depth"] > match:
                container["active"] = False
        del self.stack[match:]

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        self._append(data)


def _nodes(value):
    pending = [value]
    visited = 0
    while pending and visited < 10_000:
        node = pending.pop()
        visited += 1
        if isinstance(node, dict):
            yield node
            pending.extend(value for value in node.values() if isinstance(value, (dict, list)))
        elif isinstance(node, list):
            pending.extend(node)


def _urls(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [entry for key in ("@id", "url") if isinstance((entry := value.get(key)), str)]
    if isinstance(value, list):
        return [url for entry in value for url in _urls(entry)]
    return []


def extract_article(html: str, source: Source, expected_id: str, final_url: str, min_chars: int = 200) -> dict:
    expected = (source.key, expected_id)
    result = {
        "status": "body_not_found", "reason": None, "body": None,
        "body_kind": "publisher_html", "extraction_method": None,
        "extracted_characters": 0, "canonical_url": None, "page_title": None,
        "page_published_at_raw": None, "identity": {"expected_article_id": expected_id, "page_article_id": None, "evidence": []},
        "fulltext_completeness_verified": False, "extraction_warnings": [],
    }

    def fail(status, reason):
        result.update(status=status, reason=reason)
        return result

    if article_identity(final_url) != expected:
        return fail("id_mismatch", "final_url_article_id_differs")
    doc = _Document(source)
    doc.feed(html)
    doc.close()
    result["page_title"] = doc.title or None
    result["page_published_at_raw"] = doc.published_at_raw
    for kind, value in doc.urls:
        url = urljoin(final_url, value)
        if article_identity(url) != expected:
            return fail("id_mismatch", f"{kind}_article_id_differs_or_unrecognized")
        result["identity"]["evidence"].append({"kind": kind, "url": url})
        if result["canonical_url"] is None or kind == "canonical":
            result["canonical_url"] = url

    candidates = []
    for script in doc.json_scripts:
        try:
            value = json.loads(script)
        except (ValueError, RecursionError):
            result["extraction_warnings"].append("invalid_json_ld")
            continue
        for node in _nodes(value):
            types = node.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if not isinstance(types, list) or not any(isinstance(kind, str) and kind.rsplit("/", 1)[-1] in ARTICLE_TYPES for kind in types):
                continue
            node_urls = [urljoin(final_url, url) for key in ("url", "mainEntityOfPage", "@id") for url in _urls(node.get(key))]
            ids = [article_identity(url) for url in node_urls]
            paywall = node.get("isAccessibleForFree") is False or str(node.get("isAccessibleForFree", "")).lower() == "false"
            if paywall and ((ids and all(identity == expected for identity in ids)) or
                            (not node_urls and result["identity"]["evidence"])):
                return fail("paywall", "article_is_not_accessible_for_free")
            if not ids or any(identity != expected for identity in ids):
                continue
            result["identity"]["evidence"].append({"kind": "json_ld", "url": node_urls[0]})
            if result["canonical_url"] is None:
                result["canonical_url"] = node_urls[0]
            if not result["page_title"] and isinstance(node.get("headline"), str):
                result["page_title"] = plain_text(node["headline"])
            body = node.get("articleBody")
            if isinstance(body, str) and body.strip():
                if re.search(r"<\s*/?\s*[a-z][^>]*>|&(?:#\d+|#x[0-9a-f]+|\w+);", body, re.I):
                    body = plain_text(body)
                else:
                    body = _text([body])
                candidates.append(("json_ld.articleBody", body))

    if not result["identity"]["evidence"]:
        return fail("identity_unverified", "page_has_no_matching_canonical_or_article_metadata")
    result["identity"]["page_article_id"] = expected_id
    candidates.extend(("html." + container["selector"], _text(container["parts"])) for container in doc.containers)
    usable = [candidate for candidate in candidates if len(candidate[1]) >= min_chars]
    if not usable:
        result["extracted_characters"] = max((len(body) for _, body in candidates), default=0)
        return fail("body_too_short" if candidates else "body_not_found", "no_article_body_meets_min_chars")
    normalized = [(method, body, " ".join(body.split())) for method, body in usable]
    result["body_candidates"] = [{"method": method, "characters": len(body),
                                  "normalized_sha256": sha256(text.encode()).hexdigest()}
                                 for method, body, text in normalized]
    method, body, containing = max(normalized, key=lambda candidate: len(candidate[2]))
    if any(text not in containing for _, _, text in normalized):
        result["extraction_warnings"].append("multiple_body_representations_need_review")
        return fail("body_conflict", "article_body_candidates_disagree")
    if any(text != containing for _, _, text in normalized):
        result["extraction_warnings"].append("shorter_body_representation_detected")
    result.update(status="ok", body=body, extraction_method=method, extracted_characters=len(body))
    return result
