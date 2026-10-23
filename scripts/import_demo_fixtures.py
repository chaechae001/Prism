"""Insert missing fictional fixtures without updating existing database records.

Run from the repository root. Default: read-only plan; --apply: atomic insert.
"""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text
from app.db import get_engine
from app.repository import FixtureRepository


def import_missing(connection, stories, *, apply=False):
    existing = {r.id: r for r in connection.execute(
        text("SELECT id,title,is_demo FROM public.stories")
    )}
    publishers = dict(connection.execute(text("SELECT id,name FROM public.publishers")).all())
    missing = []
    wanted_publishers = {}
    for story in stories:
        if not story.is_demo or story.coverage.label_status != "demo":
            raise ValueError("Only fictional demo fixtures are supported")
        for article in story.articles:
            if not article.is_demo or urlparse(str(article.url)).hostname != "example.com":
                raise ValueError("Only fictional example.com articles are supported")
        old = existing.get(story.id)
        if old is not None:
            if not old.is_demo or old.title != story.title:
                raise ValueError("Story ID conflicts with different existing content")
            continue
        missing.append(story)
        for article in story.articles:
            name = wanted_publishers.setdefault(article.publisher_id, article.publisher_name)
            if name != article.publisher_name or publishers.get(article.publisher_id, name) != name:
                raise ValueError("Publisher ID conflicts with a different name")
    result = {
        "applied": apply,
        "existing_stories_skipped": len(stories) - len(missing),
        "stories_to_insert": len(missing),
        "articles_to_insert": sum(len(s.articles) for s in missing),
        "publishers_to_insert": len(wanted_publishers.keys() - publishers.keys()),
    }
    # Fail before writing if an article ID or URL is already used elsewhere.
    for story in missing:
        for article in story.articles:
            if connection.execute(text(
                "SELECT 1 FROM public.articles WHERE id=:id OR canonical_url=:url"
            ), {"id": article.id, "url": str(article.url)}).first():
                raise ValueError("Article ID or URL is already in use")
    if not apply:
        return result
    for pid, name in wanted_publishers.items():
        if pid not in publishers:
            connection.execute(text("""
                INSERT INTO public.publishers(id,name,group_id)
                VALUES (:id,:name,:group_id)
            """), {"id": pid, "name": name, "group_id": f"demo-group-{pid}"})
    for story in missing:
        data = story.model_dump()
        data.update(
            summary_status=story.summary.status,
            summary=json.dumps(story.summary.model_dump(mode="json", exclude={"status"}), ensure_ascii=False),
            perspectives=json.dumps([p.model_dump(mode="json") for p in story.perspectives], ensure_ascii=False),
        )
        connection.execute(text("""
            INSERT INTO public.stories
            (id,title,dek,category,keywords,visual,public_interest,is_demo,
             summary_status,summary,perspectives,label_status,updated_at,published_at)
            VALUES (:id,:title,:dek,:category,:keywords,:visual,:public_interest,true,
                    :summary_status,CAST(:summary AS jsonb),CAST(:perspectives AS jsonb),
                    'demo',:updated_at,:updated_at)
        """), data)
        for article in story.articles:
            params = article.model_dump()
            params["url"] = str(article.url)
            connection.execute(text("""
                INSERT INTO public.articles
                (id,publisher_id,canonical_url,title,framing,published_at,is_demo,publish_allowed)
                VALUES (:id,:publisher_id,:url,:title,:framing,:published_at,true,true)
            """), params)
            connection.execute(text("""
                INSERT INTO public.story_articles(story_id,article_id,same_event_verified)
                VALUES (:story,:article,true)
            """), {"story": story.id, "article": article.id})
    return result


def main():
    parser = argparse.ArgumentParser(description="누락된 UI 검증용 가상 뉴스 추가")
    parser.add_argument("--apply", action="store_true", help="실제 DB에 추가합니다. 기본은 읽기 전용 계획입니다.")
    args = parser.parse_args()
    try:
        stories = FixtureRepository().all()
        with get_engine().begin() as connection:
            result = import_missing(connection, stories, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Never print connection URLs, query parameters or credentials.
        print(json.dumps({"error_type": type(exc).__name__, "message": "설정·스키마·ID 충돌을 확인해주세요. 실패한 추가 작업은 취소됩니다."}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
