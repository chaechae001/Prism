"""Real PostgreSQL tests. Only an explicitly named loopback test DB is accepted."""

import json
import os
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, patch

import psycopg
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.app.api import app
from backend.app import connection_api, connection_repository
from backend.app.news_repository import get_news_from_db, list_news_from_db
from backend.app.models import AnalystBatch
from backend.app.rss.demo_db import load_demo
from backend.app.rss.reader import RSSReader
from backend.app.llm.schemas import SummaryDraft, SummaryResult
from backend.app.llm.elice_settings import EliceSettings
from backend.app.services.body_import import import_bodies
from backend.app.services.article_context import load_bodies
from backend.app.services.summaries import (
    generate_summary,
    approve_summary,
    StaleSummaryError,
)
from backend.app.services.rss_projection import prepare_rss_story

ROOT = Path(__file__).resolve().parents[2]
TEST_URL = os.getenv("PRISM_TEST_DATABASE_URL", "")


@unittest.skipUnless(
    TEST_URL, "Set PRISM_TEST_DATABASE_URL to a disposable loopback prism_test DB"
)
class DatabaseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_URL)
        if (
            url.host not in {"127.0.0.1", "localhost", "::1"}
            or url.database != "prism_test"
        ):
            raise ValueError(
                "Integration tests only accept a loopback prism_test database"
            )
        cls.engine = create_engine(TEST_URL, hide_parameters=True)
        # Dedicated fresh test database; never runs against the Supabase project.
        with psycopg.connect(
            TEST_URL.replace("postgresql+psycopg://", "postgresql://"), autocommit=True
        ) as c:
            c.execute(
                "CREATE ROLE anon; CREATE ROLE authenticated; CREATE SCHEMA auth; "
                "CREATE TABLE auth.users(id uuid PRIMARY KEY); "
                "CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'SELECT NULL::uuid'"
            )
            c.execute((ROOT / "database/schema.draft.sql").read_text(encoding="utf-8"))
            c.execute(
                (
                    ROOT / "database/migrations/20261022_001_add_rss_tables.sql"
                ).read_text(encoding="utf-8")
            )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.engine.begin() as c:
            c.execute(
                text(
                    "TRUNCATE public.stories,public.articles,public.publishers,private.raw_articles CASCADE"
                )
            )
        with psycopg.connect(
            TEST_URL.replace("postgresql+psycopg://", "postgresql://"), autocommit=True
        ) as c:
            c.execute((ROOT / "database/seed_demo.sql").read_text(encoding="utf-8"))
        self.settings = EliceSettings(
            api_url="https://example.test/id/v1/chat/completions",
            api_key="unit-test-key",
        )

    def batch(self, ids=None, uses=None):
        sql = "SELECT a.*,p.group_id FROM public.articles a JOIN public.publishers p ON p.id=a.publisher_id"
        with self.engine.connect() as c:
            rows = c.execute(text(sql)).mappings().all()
        articles = []
        for row in rows:
            if ids and row["id"] not in ids:
                continue
            body = (
                "[가상 본문] "
                + row["title"]
                + " 운영 기간은 3개월이며 추가 예산은 미공개입니다."
            )
            articles.append(
                {
                    "id": row["id"],
                    "canonical_url": row["canonical_url"],
                    "publisher_id": row["publisher_id"],
                    "publisher_group_id": row["group_id"],
                    "title": row["title"],
                    "text": body,
                    "published_at": row["published_at"],
                    "collected_at": datetime.now(timezone.utc),
                    "category": "technology",
                    "content_hash": sha256(body.encode()).hexdigest(),
                    "license_status": "allowed",
                    "allowed_uses": uses
                    or ["collect", "store", "summarize", "publish_summary"],
                }
            )
        return AnalystBatch.model_validate(
            {
                "schema_version": "1.0",
                "batch_id": "integration-test",
                "articles": articles,
            }
        )

    def generated(self, article):
        return SummaryResult(
            article_id=article.id,
            summary=SummaryDraft(
                title="[가상] 기사 요약",
                bullets=[
                    {"text": "3개월 시범 운영 계획이다.", "article_ids": [article.id]}
                ],
                perspectives=[],
                unknowns=["추가 예산은 미공개"],
            ),
            model_version="test-generated-model",
            prompt_version="article-summary-v2",
            is_mock=False,
            is_demo=True,
        )

    def test_published_story_and_three_articles_keep_contract(self):
        story = get_news_from_db("story-001", engine=self.engine)
        self.assertEqual(len(story["articles"]), 3)
        self.assertEqual(list_news_from_db(engine=self.engine)[0]["id"], "story-001")
        self.assertNotIn("raw_text", json.dumps(story))

    def test_frontend_queries_categories_and_detail_on_db(self):
        with patch("backend.app.news_repository.get_engine", return_value=self.engine):
            snapshot = connection_repository.load_snapshot("supabase")
        app.dependency_overrides[connection_api.get_snapshot] = lambda: snapshot
        try:
            client = TestClient(app)
            feed = client.get("/api/v1/stories?q=&mode=balanced&diversity=70&limit=6")
            self.assertEqual(feed.status_code, 200)
            self.assertEqual(feed.json()["total"], 1)
            self.assertEqual(client.get("/api/v1/categories").status_code, 200)
            self.assertEqual(
                len(
                    client.get("/api/v1/stories/story-001").json()["story"]["articles"]
                ),
                3,
            )
        finally:
            app.dependency_overrides.clear()

    def test_null_framing_is_mapped_and_empty_story_is_held(self):
        with self.engine.begin() as c:
            c.execute(text("UPDATE public.articles SET framing=NULL"))
        self.assertEqual(
            get_news_from_db("story-001", engine=self.engine)["articles"][0]["framing"],
            "쟁점 분류 전",
        )
        with self.engine.begin() as c:
            c.execute(text("UPDATE public.articles SET publish_allowed=false"))
        self.assertIsNone(get_news_from_db("story-001", engine=self.engine))

    def test_withdrawn_source_holds_stale_summary(self):
        with self.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE public.articles SET publish_allowed=false WHERE id='story-001-a1'"
                )
            )
        story = get_news_from_db("story-001", engine=self.engine)
        self.assertEqual(story["summary"]["status"], "pending")
        self.assertEqual(story["summary"]["bullets"], [])

    def test_body_import_preserves_ids_and_is_idempotent(self):
        batch = self.batch()
        first = import_bodies(batch, engine=self.engine)
        second = import_bodies(batch, engine=self.engine)
        self.assertTrue(all(row["changed"] for row in first))
        self.assertFalse(any(row["changed"] for row in second))
        bodies = load_bodies([a.id for a in batch.articles], engine=self.engine)
        self.assertEqual(len(bodies), 3)

    def test_invalid_hash_rolls_back_entire_body_batch(self):
        batch = self.batch()
        batch.articles[-1].content_hash = "wrong-hash"
        with self.assertRaises(ValueError):
            import_bodies(batch, engine=self.engine)
        with self.engine.connect() as c:
            self.assertEqual(
                c.execute(
                    text("SELECT count(*) FROM private.raw_articles")
                ).scalar_one(),
                0,
            )

    def test_unpermitted_body_is_not_used_in_dm(self):
        batch = self.batch(uses=["collect", "store"])
        import_bodies(batch, engine=self.engine)
        self.assertEqual(
            load_bodies([a.id for a in batch.articles], engine=self.engine), {}
        )

    def test_tampered_body_hash_is_rejected(self):
        batch = self.batch()
        import_bodies(batch, engine=self.engine)
        with self.engine.begin() as c:
            c.execute(text("UPDATE private.raw_articles SET raw_text='modified'"))
        with self.assertRaises(ValueError):
            load_bodies([a.id for a in batch.articles], engine=self.engine)

    def test_summary_draft_cache_and_explicit_approval(self):
        import_bodies(self.batch(), engine=self.engine)
        generate = Mock(side_effect=self.generated)
        draft = generate_summary(
            "story-001", engine=self.engine, settings=self.settings, generate=generate
        )
        self.assertEqual(draft["status"], "pending")
        self.assertEqual(generate.call_count, 3)
        cached = generate_summary(
            "story-001", engine=self.engine, settings=self.settings, generate=generate
        )
        self.assertTrue(cached["cached"])
        self.assertEqual(generate.call_count, 3)
        approve_summary(draft["id"], engine=self.engine)
        story = get_news_from_db("story-001", engine=self.engine)
        self.assertEqual(story["summary"]["status"], "ready")
        self.assertEqual(len(story["summary"]["bullets"]), 3)
        self.assertIn("통합 요약 아님", story["dek"])

    def test_body_change_prevents_stale_approval(self):
        batch = self.batch()
        import_bodies(batch, engine=self.engine)
        draft = generate_summary(
            "story-001",
            engine=self.engine,
            settings=self.settings,
            generate=self.generated,
        )
        batch.articles[0].text += " 정정 내용"
        batch.articles[0].content_hash = sha256(
            batch.articles[0].text.encode()
        ).hexdigest()
        import_bodies(batch, engine=self.engine)
        with self.assertRaises(StaleSummaryError):
            approve_summary(draft["id"], engine=self.engine)

    def test_missing_bodies_do_not_call_provider(self):
        generate = Mock()
        with self.assertRaises(ValueError):
            generate_summary(
                "story-001",
                engine=self.engine,
                settings=self.settings,
                generate=generate,
            )
        generate.assert_not_called()

    def test_rss_repeat_storage_and_original_dates_preserved(self):
        load_demo(self.engine, verify_repeat=True)
        rows = RSSReader(self.engine).list_records(limit=100)
        self.assertEqual(len(rows), 5)
        self.assertEqual(sum(row["published_at"] is None for row in rows), 1)
        self.assertEqual(
            len(get_news_from_db("story-001", engine=self.engine)["articles"]), 3
        )
        with self.assertRaises(ValueError):
            prepare_rss_story(rows[0]["id"], engine=self.engine)

    def test_rss_projection_preserves_database_article_id(self):
        load_demo(self.engine)
        rights = json.dumps(
            {
                key: "allowed"
                for key in (
                    "collect",
                    "store",
                    "summarize",
                    "publish_summary",
                    "display_image",
                )
            }
        )
        with self.engine.begin() as c:
            c.execute(
                text("UPDATE private.rss_items SET rights_snapshot=CAST(:r AS jsonb)"),
                {"r": rights},
            )
            c.execute(
                text("UPDATE private.rss_feeds SET rights=CAST(:r AS jsonb)"),
                {"r": rights},
            )
            row = (
                c.execute(
                    text(
                        "SELECT id,article_id FROM private.rss_items WHERE article_id IS NOT NULL LIMIT 1"
                    )
                )
                .mappings()
                .one()
            )
        projection = prepare_rss_story(row["id"], engine=self.engine)
        self.assertEqual(projection["article_id"], row["article_id"])
        self.assertFalse(projection["published"])
        self.assertIsNone(get_news_from_db(projection["story_id"], engine=self.engine))

    def test_existing_dm_reads_permitted_bodies_with_original_ids(self):
        from backend.app.chat import router as chat

        import_bodies(self.batch(), engine=self.engine)
        story = get_news_from_db("story-001", engine=self.engine)
        from backend.app.models import Story

        with (
            patch.dict(os.environ, {"PRISM_DATA_SOURCE": "supabase"}),
            patch(
                "backend.app.services.article_context.get_engine",
                return_value=self.engine,
            ),
        ):
            context = chat.context_for(Story.model_validate(story))
        self.assertEqual(len(context["bodies"]), 3)
        self.assertEqual(
            {b["article_id"] for b in context["bodies"]},
            {a["id"] for a in story["articles"]},
        )
        self.assertIn("본문", context["notice"])

    def test_body_revocation_blocks_existing_draft(self):
        batch = self.batch()
        import_bodies(batch, engine=self.engine)
        draft = generate_summary(
            "story-001",
            engine=self.engine,
            settings=self.settings,
            generate=self.generated,
        )
        batch.articles[0].allowed_uses = ["collect", "store"]
        import_bodies(batch, engine=self.engine)
        with self.assertRaises(ValueError):
            approve_summary(draft["id"], engine=self.engine)


if __name__ == "__main__":
    unittest.main()
