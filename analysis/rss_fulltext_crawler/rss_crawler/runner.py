"""Run a local collection batch and export reviewable, versioned JSON files."""

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from .extraction import extract_article
from .network import CrawlClient, FetchError, decode_html
from .parsing import Source, canonical_url, parse_feed
from .selection import SelectionPolicy


SCHEMA_VERSION = "rss-fulltext/1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def collect(sources: list[Source], limit: int = 3, min_chars: int = 200,
            client: CrawlClient | None = None, progress=None, *, selection: SelectionPolicy | None = None) -> dict:
    if not 1 <= limit <= 100 or not 1 <= min_chars <= 10_000:
        raise ValueError("invalid_collection_limits")
    if selection is not None and not isinstance(selection, SelectionPolicy):
        raise ValueError('selection must be a SelectionPolicy')
    client = client if client is not None else CrawlClient()
    results, source_reports = [], []
    seen_feeds, seen_articles = set(), set()
    duplicate_articles = 0
    for source in sources:
        feed_key = canonical_url(source.feed_url)
        if feed_key in seen_feeds:
            continue
        seen_feeds.add(feed_key)
        report = {"source": source.key, "publisher": source.publisher, "rss_url": source.feed_url,
                  "status": "ok", "rss_items_total": 0, "selected_items": 0,
                  "duplicate_items_skipped": 0, "fetched_at": None, "rss_sha256": None}
        source_reports.append(report)
        if selection is not None:
            report.update(excluded_items=[], excluded_by_reason={})
        if progress:
            progress(f"[{source.key}] Reading RSS")
        try:
            response = client.get(source.feed_url, 5_000_000)
            report["fetched_at"] = _now()
            report["rss_sha256"] = sha256(response.body).hexdigest()
            items = parse_feed(response.body, source)
            report["rss_items_total"] = len(items)
        except FetchError as exc:
            report.update(status=exc.code, http_status=exc.http_status)
            if progress:
                progress(f"[{source.key}] RSS skipped: {exc.code}")
            continue
        except ValueError as exc:
            report.update(status="invalid_rss", reason=str(exc))
            continue
        for item in items:
            identity = (source.key, item["publisher_article_id"])
            if item["publisher_article_id"] and identity in seen_articles:
                duplicate_articles += 1
                report["duplicate_items_skipped"] += 1
                continue
            if selection is not None:
                reason = selection.reason(item)
                if reason is None and report['selected_items'] >= limit:
                    reason = 'eligible_over_limit'
                if reason is not None:
                    report['excluded_items'].append({key: item.get(key) for key in
                        ('article_id', 'publisher_article_id', 'published_at', 'rss_position', 'issue')}
                        | {'reason': reason})
                    counts = report['excluded_by_reason']
                    counts[reason] = counts.get(reason, 0) + 1
                    continue
            elif report["selected_items"] >= limit:
                break
            if item["publisher_article_id"] and item["issue"] is None:
                seen_articles.add(identity)
            report["selected_items"] += 1
            record = {
                **item, "rss_url": source.feed_url, "rss_fetched_at": report["fetched_at"],
                "collected_at": _now(), "status": item["issue"] or "pending",
                "reason": item["issue"], "body": None, "body_kind": None,
                "resolved_url": None, "canonical_url": None, "http_status": None,
                "content_hash": None, "body_sha256": None, "html_sha256": None,
                "rights": {"license_status": "unknown", "allowed_uses": []},
            }
            if item["issue"] is None:
                try:
                    response = client.get(item["url"], 3_000_000, identity)
                    record.update(resolved_url=response.url, http_status=response.status,
                                  html_sha256=sha256(response.body).hexdigest())
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
                    if content_type and content_type not in {"text/html", "application/xhtml+xml"}:
                        raise FetchError("unexpected_content_type", response.status)
                    record.update(extract_article(decode_html(response), source, item["publisher_article_id"], response.url, min_chars))
                    if record["status"] == "ok":
                        record["body_sha256"] = sha256(record["body"].encode()).hexdigest()
                        record["content_hash"] = sha256(f'{record["title"]}\n{record["body"]}'.strip().encode()).hexdigest()
                except FetchError as exc:
                    record.update(status=exc.code, reason=exc.code, http_status=exc.http_status or record["http_status"])
                except (ValueError, RecursionError) as exc:
                    record.update(status="extraction_error", reason=type(exc).__name__)
            results.append(record)
            if progress:
                progress(f'[{source.key}] {item["publisher_article_id"] or "invalid-item"}: {record["status"]} ({len(record["body"] or "")} chars)')
    summary = {
        "feed_count": len(source_reports),
        "feed_status_counts": dict(Counter(report["status"] for report in source_reports)),
        "rss_items_total": sum(report["rss_items_total"] for report in source_reports),
        "selected_articles": len(results), "extracted_count": sum(item["status"] == "ok" for item in results),
        "article_status_counts": dict(Counter(item["status"] for item in results)),
        "duplicate_articles_skipped": duplicate_articles, "http_requests": client.requests_made,
    }
    if selection is not None:
        summary['excluded_articles'] = sum(len(report['excluded_items']) for report in source_reports)
    return {
        "schema_version": SCHEMA_VERSION, "created_at": _now(),
        "collection": {"input": "publisher_rss", "body_source": "publisher_html", "limit_per_feed": limit,
                       "min_body_characters": min_chars, "robots_policy_agents": ["AINewsFulltextBot", "GPTBot"],
                       "automatic_publication_allowed": False, "database_writes": 0,
                       **({'selection': selection.to_dict()} if selection is not None else {})},
        "summary": summary, "source_reports": source_reports, "results": results,
    }


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".json.partial")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    temporary.replace(path)


def write_run(result: dict, output_root: Path | str) -> Path:
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-"), dir=root))
    _write_json(run / "results.json", result)
    _write_json(run / "articles.json", {
        "schema_version": SCHEMA_VERSION, "created_at": result["created_at"],
        "collection": result["collection"],
        "articles": [item for item in result["results"] if item["status"] == "ok"],
    })
    _write_json(run / "summary.json", {"schema_version": SCHEMA_VERSION, "created_at": result["created_at"],
                                       **result["summary"], "source_reports": result["source_reports"]})
    return run
