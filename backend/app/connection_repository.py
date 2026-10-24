"""Swappable read boundary. No schema writes or RSS collection belongs here."""
import importlib
import json
import os
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from .models import Story
from .repository import FixtureRepository
from .rss_preview import RssRecord, rss_to_story

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {"fixture", "rss-fixture", "db-demo", "rss-reader", "supabase", "cluster-local", "cluster-db"}


@dataclass
class Snapshot:
    stories: list[Story]
    version: str
    is_mock: bool
    source: str
    notes: list[str] = field(default_factory=list)
    preview: bool = False


def _version(prefix, stories):
    content = [s.model_dump(mode="json") for s in sorted(stories, key=lambda s: s.id)]
    digest = sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


def load_snapshot(source: str | None = None) -> Snapshot:
    source = source or os.getenv("PRISM_DATA_SOURCE", "fixture")
    if source not in SOURCES:
        raise ValueError("Invalid PRISM_DATA_SOURCE")
    if source == "fixture":
        repo = FixtureRepository()
        return Snapshot(repo.all(), repo.dataset_version, True, source, ["가상 사건·기사로 검증하는 HTTP 연결입니다."])
    if source == "cluster-local":
        from .cluster_preview import load_cluster_preview
        folder = os.getenv("CLUSTER_RESULTS_DIR", str(ROOT / "testdata/clustering/scheduled-sbs"))
        default_images = Path(folder) / "images.json"
        images = os.getenv("CLUSTER_IMAGES_PATH") or (default_images if default_images.is_file() else None)
        stories, version, notes = load_cluster_preview(folder, image_manifest=images)
        return Snapshot(stories, version, False, source, notes, preview=True)
    if source == "cluster-db":
        from .cluster_feed import load_cluster_feed
        stories,version,notes=load_cluster_feed()
        return Snapshot(stories,version,bool(stories) and all(s.is_demo for s in stories),source,notes,preview=True)
    if source == "supabase":
        reader = importlib.import_module(".news_repository", __package__)
        stories = [Story.model_validate(row) for row in reader.list_news_from_db()]
        return Snapshot(stories, _version("supabase", stories), bool(stories) and all(s.is_demo for s in stories), source,
                        ["DB에 게시된 사건과 공개 가능한 출처를 조회합니다.",
                         "개발용 조회 범위는 최대 500개 사건입니다. 초과하면 페이지 조회 전환이 필요합니다."])
    if source == "db-demo":
        # Optional DB reader. Import or DB failures must not fall back to fixtures.
        reader = importlib.import_module(".news_repository", __package__)
        row = reader.get_news_from_db("story-001")
        stories = [Story.model_validate(row)] if row is not None else []
        return Snapshot(stories, _version("db-demo", stories), all(s.is_demo for s in stories), source,
                        ["개발 DB의 story-001 조회입니다. 실제 RSS 수집/AI 실행을 의미하지 않습니다."])
    if source == "rss-fixture":
        path = Path(os.getenv("RSS_FIXTURE_PATH", str(ROOT / "docs/architecture/rss-record-v1.examples.json")))
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
    else:
        reader = importlib.import_module(".rss.reader", __package__)
        rows = reader.list_rss_records(limit=100)
    if not isinstance(rows, list):
        raise TypeError("RSS reader must return a list")
    article_links = reader.list_rss_article_links(limit=100) if source == "rss-reader" else {}
    stories, seen, skipped = [], set(), {}
    for row in rows:
        try:
            record = RssRecord.model_validate(row)
            if source == "rss-fixture" and not record.is_demo:
                raise ValueError("RSS fixture must be synthetic")
            article_id = article_links.get(str(record.canonical_url))
            if source == "rss-reader" and not article_id:
                story, reason = None, "unlinked_database_article"
            else:
                story, reason = rss_to_story(record, article_id=article_id)
        except ValidationError:
            story, reason = None, "invalid_record"
        if story is None:
            skipped[reason] = skipped.get(reason, 0) + 1
        elif story.id not in seen:
            stories.append(story)
            seen.add(story.id)
    notes = ["RSS 원문 기사 미리보기입니다. 군집분석·AI 요약·중립성 평가는 실행하지 않았습니다.",
             "날짜 미확인·미래 발행·공개 이용 범위 미확인 항목은 화면용 Story 변환에서 보류합니다."]
    if skipped:
        notes.append("보류: " + ", ".join(f"{key}={value}" for key, value in sorted(skipped.items())))
    if source == "rss-reader":
        notes.append("현재 reader에서 최대 100개를 읽는 개발용 범위입니다. total은 이 범위의 표시 가능 건수입니다.")
    return Snapshot(stories, _version(source, stories), source == "rss-fixture" or (bool(stories) and all(s.is_demo for s in stories)),
                    source, notes, preview=True)
