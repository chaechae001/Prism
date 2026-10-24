"""Real PostgreSQL tests. Only an explicitly named loopback test DB is accepted."""

import json
import os
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory

import psycopg
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from backend.app.api import app
from backend.app import connection_api, connection_repository
from backend.app.news_repository import get_news_from_db, list_news_from_db
from backend.app.models import AnalystBatch
from backend.app.rss.demo_db import load_demo
from backend.app.rss.reader import RSSReader
from backend.app.llm.schemas import SummaryDraft, SummaryResult
from backend.app.llm.elice_settings import EliceSettings
from backend.app.services.body_import import import_bodies
from backend.app.services.analyst_validation import check_batch, plan_import, InvalidAnalystBatch
from backend.app.services.article_intake import intake_articles, IntakeConflict
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
                "CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role; CREATE SCHEMA auth; "
                "CREATE TABLE auth.users(id uuid PRIMARY KEY); "
                "CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'SELECT NULL::uuid'"
            )
            c.execute((ROOT / "database/schema.draft.sql").read_text(encoding="utf-8"))
            c.execute(
                (
                    ROOT / "database/migrations/20261022_001_add_rss_tables.sql"
                ).read_text(encoding="utf-8")
            )
            for filename in ('20261023_001_cluster_storage.sql', '20261023_002_scheduled_news.sql'):
                c.execute((ROOT / 'database/migrations' / filename).read_text(encoding='utf-8'))

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

    def intake_batch(self):
        payload = self.batch(ids={"story-001-a1"}).model_dump(mode="json")
        payload["articles"][0]["canonical_url"] = "https://example.com/intake/new-article"
        return AnalystBatch.model_validate(payload)

    def test_intake_plan_does_not_create_new_article_or_body(self):
        report = intake_articles(self.intake_batch(), engine=self.engine)
        self.assertTrue(report["ready_for_intake"])
        self.assertEqual(report["plan"]["new_article_count"], 1)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM public.articles")).scalar_one(), 3)
            self.assertEqual(c.execute(text("SELECT count(*) FROM private.raw_articles")).scalar_one(), 0)

    def test_intake_creates_unpublished_article_and_matching_body_atomically(self):
        batch = self.intake_batch()
        report = intake_articles(batch, engine=self.engine, apply=True, is_demo=True)
        self.assertTrue(report["written"])
        self.assertEqual(report["body_changed_count"], 1)
        with self.engine.connect() as c:
            row = c.execute(text("""
                SELECT a.id,a.publish_allowed,a.is_demo,r.id AS body_id,r.raw_text
                FROM public.articles a JOIN private.raw_articles r USING(canonical_url)
                WHERE a.canonical_url=:url
            """), {"url": str(batch.articles[0].canonical_url)}).mappings().one()
            self.assertFalse(row["publish_allowed"])
            self.assertTrue(row["is_demo"])
            self.assertEqual(row["id"], row["body_id"])
            self.assertNotEqual(row["id"], batch.articles[0].id)
            self.assertEqual(row["raw_text"], batch.articles[0].text)
        self.assertEqual(len(list_news_from_db(engine=self.engine)), 1)

    def test_repeated_intake_does_not_duplicate_or_change_body_version(self):
        batch = self.intake_batch()
        intake_articles(batch, engine=self.engine, apply=True, is_demo=True)
        report = intake_articles(batch, engine=self.engine, apply=True, is_demo=True)
        self.assertEqual(report["plan"]["new_article_count"], 0)
        self.assertEqual(report["body_changed_count"], 0)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM public.articles")).scalar_one(), 4)
            self.assertEqual(c.execute(text("SELECT count(*) FROM private.raw_articles")).scalar_one(), 1)

    def test_intake_group_conflict_is_reported_and_rejected(self):
        payload = self.intake_batch().model_dump(mode="json")
        payload["articles"][0]["publisher_group_id"] = "different-group"
        batch = AnalystBatch.model_validate(payload)
        report = intake_articles(batch, engine=self.engine)
        self.assertFalse(report["ready_for_intake"])
        self.assertEqual(report["intake_errors"][0]["code"], "PUBLISHER_GROUP_MISMATCH")
        with self.assertRaises(IntakeConflict):
            intake_articles(batch, engine=self.engine, apply=True)

    def test_intake_unknown_publisher_is_not_automatically_registered(self):
        payload = self.intake_batch().model_dump(mode="json")
        payload["articles"][0]["publisher_id"] = "unknown-publisher"
        batch = AnalystBatch.model_validate(payload)
        with self.assertRaises(IntakeConflict):
            intake_articles(batch, engine=self.engine, apply=True)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM public.publishers")).scalar_one(), 3)

    def test_intake_failure_rolls_back_metadata_bodies_and_story_version(self):
        from backend.app.services.body_import import _store_bodies

        payload = self.batch(ids={"story-001-a1"}).model_dump(mode="json")
        payload["articles"].extend(self.intake_batch().model_dump(mode="json")["articles"])
        payload["articles"][1]["id"] = "new-input-id"
        batch = AnalystBatch.model_validate(payload)
        def fail_after_store(connection, rows):
            _store_bodies(connection, rows)
            raise RuntimeError("simulated interruption")
        with patch("backend.app.services.article_intake._store_bodies", side_effect=fail_after_store):
            with self.assertRaises(RuntimeError):
                intake_articles(batch, engine=self.engine, apply=True)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM public.articles")).scalar_one(), 3)
            self.assertEqual(c.execute(text("SELECT count(*) FROM private.raw_articles")).scalar_one(), 0)
            self.assertEqual(c.execute(text("SELECT event_version FROM public.stories WHERE id='story-001'")).scalar_one(), 1)

    def test_demo_intake_cannot_modify_real_article(self):
        with self.engine.begin() as c:
            c.execute(text("UPDATE public.articles SET is_demo=false WHERE id='story-001-a1'"))
        batch = self.batch(ids={"story-001-a1"})
        with self.assertRaises(IntakeConflict):
            intake_articles(batch, engine=self.engine, apply=True, is_demo=True)

    def test_analyst_plan_reads_existing_mapping_without_writing(self):
        report = plan_import(check_batch(self.batch()), engine=self.engine)
        self.assertTrue(report["ready_for_import"])
        self.assertEqual(report["mapping"]["matched_count"], 3)
        self.assertFalse(report["written"])
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM private.raw_articles")).scalar_one(), 0)

    def test_analyst_plan_identifies_new_url_without_creating_article(self):
        batch = self.batch().model_dump(mode="json")
        batch["articles"][0]["canonical_url"] = "https://example.com/not-registered"
        report = plan_import(check_batch(batch), engine=self.engine)
        self.assertFalse(report["ready_for_import"])
        self.assertEqual(report["mapping"]["missing_article_indices"], [0])
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM public.articles")).scalar_one(), 3)

    def test_duplicate_batch_does_not_change_bodies_or_event_version(self):
        batch = self.batch()
        duplicate = batch.model_copy(update={"articles": [batch.articles[0], batch.articles[0]]})
        with self.assertRaises(InvalidAnalystBatch):
            import_bodies(duplicate, engine=self.engine)
        with self.engine.connect() as c:
            self.assertEqual(c.execute(text("SELECT count(*) FROM private.raw_articles")).scalar_one(), 0)
            self.assertEqual(c.execute(text("SELECT event_version FROM public.stories WHERE id='story-001'")).scalar_one(), 1)

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

    def test_supplied_cluster_bundle_roundtrip_preserves_public_news(self):
        from backend.app.cluster_store import prepare_bundle
        from backend.app.cluster_store.repository import store_bundle
        from backend.app.scheduled_news.repository import Repository
        from backend.app.cluster_feed import load_cluster_feed

        folder = ROOT / 'testdata/clustering/scheduled-sbs'
        bundle = prepare_bundle(folder, namespace='integration-snapshot', image_manifest=folder / 'images.json')
        before = list_news_from_db(engine=self.engine)
        result = store_bundle(bundle, engine=self.engine)
        self.assertIn(result['status'], {'stored', 'already_stored'})
        repeated = store_bundle(bundle, engine=self.engine)
        self.assertEqual(repeated['status'], 'already_stored')
        self.assertEqual(repeated['database_writes'], 0)
        repo = Repository(engine=self.engine)
        repo.store(bundle, input_hash='a' * 64, analyzed_at=datetime.now(timezone.utc))
        stories, _, _ = load_cluster_feed(namespace='integration-snapshot', engine=self.engine)
        self.assertEqual(len(stories), 20)
        self.assertEqual(sum(len(s.articles) for s in stories), 29)
        self.assertTrue(all(s.summary.status == 'pending' for s in stories))
        self.assertEqual(list_news_from_db(engine=self.engine), before)
        with self.engine.connect() as c:
            for role in ('anon', 'authenticated', 'service_role'):
                c.execute(text(f'SET LOCAL ROLE {role}'))
                with self.assertRaises(DBAPIError) as rejected:
                    c.execute(text('SELECT raw_text FROM private.prism_cluster_articles LIMIT 1'))
                self.assertEqual(rejected.exception.orig.sqlstate, '42501')
                c.rollback()

    def active_cluster_snapshot(self, bodies=None):
        from backend.app.cluster_store import prepare_bundle
        from backend.app.scheduled_news.repository import Repository
        from backend.app.cluster_feed import load_cluster_feed
        from backend.app.connection_repository import Snapshot
        from backend.tests.test_cluster_preview import source_article, save

        namespace = 'chat-' + sha256(self.id().encode()).hexdigest()[:16]
        if bodies is None:
            folder = ROOT / 'testdata/clustering/scheduled-sbs'
            bundle = prepare_bundle(folder, namespace=namespace, image_manifest=folder/'images.json')
        else:
            with TemporaryDirectory() as directory:
                folder = Path(directory)
                rows = []
                for identity, body in bodies.items():
                    row = source_article(identity)
                    row['body'] = body
                    row['content_hash'] = sha256(f"{row['title']}\n{body}".strip().encode()).hexdigest()
                    row['rights'] = {use:'allowed' for use in ('collect','store','summarize','publish_summary','display_image')}
                    rows.append(row)
                exported = dict(schema_version='local-news-representatives/v1',status='completed',
                    article_count=len(rows),group_count=1,automatic_publication=False,accuracy_measured=False,
                    groups=[dict(group_id='test-group',category='경제',article_count=len(rows),publisher_count=1,
                        article_ids=[r['article_id'] for r in rows],representative=rows[0],related_articles=rows[1:],
                        same_event_confirmed=False)])
                save(folder,exported,rows)
                (folder/'input.json').write_text(json.dumps({'articles':rows}),encoding='utf-8')
                bundle = prepare_bundle(folder,namespace=namespace)
        Repository(engine=self.engine).store(bundle,input_hash=bundle['payload_sha256'],analyzed_at=datetime.now(timezone.utc))
        stories,version,notes,aliases = load_cluster_feed(namespace=namespace,engine=self.engine,include_aliases=True)
        snapshot = Snapshot(stories,version,False,'cluster-db',notes,preview=True,aliases=aliases)
        return namespace,bundle,snapshot

    def test_cluster_chat_context_matches_only_selected_members_and_old_links(self):
        from backend.app.services.cluster_context import chat_cluster_bodies, ClusterContextError
        from backend.app.connection_repository import resolve_story
        namespace,_,snapshot = self.active_cluster_snapshot()
        story = max(snapshot.stories,key=lambda s:len(s.articles))
        bodies = chat_cluster_bodies(story,engine=self.engine,namespace=namespace)
        self.assertEqual({b['article_id'] for b in bodies},{a.id for a in story.articles})
        old_id = next(k for k,v in snapshot.aliases.items() if v==story.id)
        old = resolve_story(snapshot,old_id)
        self.assertEqual(old.id,old_id)
        self.assertEqual(chat_cluster_bodies(old,engine=self.engine,namespace=namespace),bodies)
        altered = story.model_copy(deep=True)
        altered.articles[0].id = 'different-news-article'
        with self.assertRaises(ClusterContextError):
            chat_cluster_bodies(altered,engine=self.engine,namespace=namespace)
        connection_api.app.dependency_overrides[connection_api.get_snapshot] = lambda:snapshot
        try:
            detail = TestClient(connection_api.app).get('/api/v1/stories/'+old_id)
            self.assertEqual(detail.status_code,200)
            self.assertEqual(detail.json()['story']['id'],old_id)
            self.assertNotIn('raw_text',detail.text)
            self.assertNotIn('body_sha256',detail.text)
        finally:
            connection_api.app.dependency_overrides.clear()

    def test_cluster_body_budget_and_excerpt_metadata(self):
        from backend.app.services.cluster_context import chat_cluster_bodies
        namespace,_,snapshot = self.active_cluster_snapshot({'a':'가'*16000,'b':'나'*16000,'c':'다'*16000})
        bodies = chat_cluster_bodies(snapshot.stories[0],engine=self.engine,namespace=namespace)
        self.assertEqual(sum(len(b['text']) for b in bodies),24000)
        self.assertEqual([b['article_id'] for b in bodies],['a','b'])
        self.assertTrue(all(b['is_excerpt'] for b in bodies))

    def test_cluster_body_permission_revocation_and_stale_namespace_fail_closed(self):
        from backend.app.services.cluster_context import chat_cluster_bodies, ClusterContextError
        namespace,bundle,snapshot = self.active_cluster_snapshot({'a':'허용된 첫 본문','b':'별도 기사 본문'})
        story = snapshot.stories[0]
        with self.engine.begin() as c:
            c.execute(text('''UPDATE private.prism_cluster_articles SET
                rights=jsonb_set(rights,'{summarize}','"denied"'),
                record=jsonb_set(record,'{rights,summarize}','"denied"')
                WHERE batch_id=:batch AND article_id='b' '''),{'batch':bundle['batch_id']})
        bodies = chat_cluster_bodies(story,engine=self.engine,namespace=namespace)
        self.assertEqual([b['article_id'] for b in bodies],['a'])
        with self.engine.begin() as c:
            c.execute(text('''UPDATE private.prism_cluster_articles SET
                rights=jsonb_set(rights,'{summarize}','"denied"'),
                record=jsonb_set(record,'{rights,summarize}','"denied"')
                WHERE batch_id=:batch'''),{'batch':bundle['batch_id']})
        with self.assertRaises(ClusterContextError):
            chat_cluster_bodies(story,engine=self.engine,namespace=namespace)
        with self.assertRaises(ClusterContextError):
            chat_cluster_bodies(story,engine=self.engine,namespace='other-namespace')

    def test_cluster_dm_uses_db_bodies_and_cites_only_the_selected_news(self):
        from unittest.mock import AsyncMock
        from backend.app.chat import router as chat
        namespace,_,snapshot = self.active_cluster_snapshot({'a':'가상 발표 내용입니다. 지원 기간은 3개월입니다.','b':'가상 지원 절차에 대한 기사입니다.'})
        story = snapshot.stories[0]
        with patch.dict(os.environ,{'PRISM_DATA_SOURCE':'cluster-db','PRISM_CLUSTER_NAMESPACE':namespace,
                'PRISM_CHAT_ENABLED':'1','PRISM_CLUSTER_CHAT_ENABLED':'1','PRISM_CHAT_PROVIDER':'openai',
                'OPENAI_API_KEY':'test-local-only','OPENAI_CHAT_MODEL':'test-model'}), \
                patch('backend.app.services.cluster_context._engine',return_value=self.engine), \
                patch.object(chat,'load_snapshot',return_value=snapshot):
            answer = chat.GroundedAnswer(answer='가상 자료의 지원 기간은 3개월입니다.',article_ids=['a'])
            with patch.object(chat,'ask_provider',new_callable=AsyncMock,return_value=answer) as provider:
                response = TestClient(app).post('/api/social/stories/'+story.id+'/chat',json={'question':'지원 기간을 알려줘'})
                self.assertEqual(response.status_code,200)
                context = json.loads(provider.await_args.args[0]['input'][0]['content'])['CONTEXT']
                self.assertEqual({b['article_id'] for b in context['bodies']},{'a','b'})
                self.assertIn('3개월',context['bodies'][0]['text'])
                self.assertNotIn('test-local-only',response.text)
            invalid = chat.GroundedAnswer(answer='다른 뉴스의 내용',article_ids=['outside-article'])
            with patch.object(chat,'ask_provider',new_callable=AsyncMock,return_value=invalid):
                response = TestClient(app).post('/api/social/stories/'+story.id+'/chat',json={'question':'요약해줘'})
                self.assertEqual(response.status_code,502)


if __name__ == "__main__":
    unittest.main()
