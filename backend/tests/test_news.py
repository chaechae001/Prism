from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import httpx
from fastapi.testclient import TestClient
from app.news.naver import NaverClient, NaverError, NaverItem, normalize, canonical_url
from app.news.models import BodyImport, Publisher


class NaverTests(unittest.TestCase):
    def test_v2_database_error_does_not_leak_credentials(self):
        from app.news_api import app

        with patch(
            "app.news.router.connect",
            side_effect=RuntimeError("postgresql://user:secret@host/db"),
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/api/v2/stories", headers={"Origin": "http://127.0.0.1:5173"}
                )
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("secret", response.text)
                self.assertEqual(
                    response.headers["X-Request-ID"],
                    response.json()["error"]["request_id"],
                )

    def item(self, **values):
        row = {
            "title": "<b>시험</b> &amp; 결과",
            "originallink": "https://press.example.com/a?id=1&utm_source=x",
            "link": "https://news.naver.com/example",
            "description": "<b>짧은</b> 검색 설명",
            "pubDate": "Thu, 22 Oct 2026 01:00:00 +0900",
        }
        row.update(values)
        return NaverItem.model_validate(row)

    def test_html_original_url_and_missing_body(self):
        p = Publisher(
            id="press", name="언론사", group_id="group", domains=["press.example.com"]
        )
        article = normalize(self.item(), "economy", [p])
        self.assertEqual(article.title, "시험 & 결과")
        self.assertEqual(article.snippet, "짧은 검색 설명")
        self.assertEqual(article.publisher.id, "press")
        self.assertEqual(str(article.canonical_url), "https://press.example.com/a?id=1")
        self.assertNotIn("body", article.model_dump())

    def test_tracking_only_is_removed(self):
        self.assertEqual(
            canonical_url("https://a.example/a?id=1&utm_x=2#x"),
            "https://a.example/a?id=1",
        )
        self.assertNotEqual(
            canonical_url("https://a.example/a?id=1"),
            canonical_url("https://a.example/a?id=2"),
        )
        with self.assertRaises(ValueError):
            canonical_url("https://secret@a.example/a")

    def test_missing_date_publisher_are_explicit(self):
        row = normalize(self.item(pubDate="bad"), "society", [])
        self.assertIsNone(row.provider_published_at)
        self.assertIsNone(row.publisher)

    def test_missing_original_link_uses_link(self):
        row = normalize(self.item(originallink=""), "society", [])
        self.assertEqual(str(row.original_url), "https://news.naver.com/example")

    def test_request_headers_and_response(self):
        def handle(request):
            self.assertEqual(request.headers["X-Naver-Client-Id"], "test-id")
            self.assertEqual(request.url.params["sort"], "date")
            self.assertNotIn("test-secret", str(request.url))
            return httpx.Response(
                200,
                json={
                    "lastBuildDate": "now",
                    "total": 1,
                    "start": 1,
                    "display": 1,
                    "items": [self.item().model_dump()],
                },
            )

        with patch.dict(
            os.environ,
            {"NAVER_CLIENT_ID": "test-id", "NAVER_CLIENT_SECRET": "test-secret"},
        ):
            with httpx.Client(transport=httpx.MockTransport(handle)) as c:
                self.assertEqual(len(NaverClient(c).search("버스").items), 1)

    def test_missing_keys_and_limits(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(NaverError, "CREDENTIALS_MISSING"):
                NaverClient().search("버스")
        for values in ({"display": 101}, {"start": 1001}, {"sort": "bad"}):
            with self.assertRaises(ValueError):
                NaverClient().search("버스", **values)

    def test_rate_limit_and_invalid_response_are_sanitized(self):
        with patch.dict(
            os.environ, {"NAVER_CLIENT_ID": "id", "NAVER_CLIENT_SECRET": "do-not-leak"}
        ):
            for response, code in [
                (httpx.Response(429, text="secret details"), "RATE_LIMITED"),
                (httpx.Response(200, text="invalid"), "INVALID_RESPONSE"),
            ]:
                with httpx.Client(
                    transport=httpx.MockTransport(lambda request: response)
                ) as c:
                    with self.assertRaisesRegex(NaverError, code) as error:
                        NaverClient(c).search("버스")
                    self.assertNotIn("secret", str(error.exception))


@unittest.skipUnless(
    os.getenv("NEWS_TEST_DATABASE_URL"),
    "Set NEWS_TEST_DATABASE_URL to the disposable local *_test database",
)
class NewsDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.rows import dict_row
        from app.news.demo import seed_demo

        cls.dsn = os.environ["NEWS_TEST_DATABASE_URL"]
        parsed = urlsplit(cls.dsn)
        if parsed.hostname not in (
            "127.0.0.1",
            "localhost",
        ) or not parsed.path.endswith("_test"):
            raise RuntimeError("Refusing DB tests outside a localhost *_test database")
        with psycopg.connect(cls.dsn, row_factory=dict_row) as c:
            if not c.execute(
                "select to_regclass('private.news_v2_articles') as t"
            ).fetchone()["t"]:
                c.execute(
                    (
                        ROOT
                        / "database/supabase/migrations/20261022055246_naver_ingestion_and_story_modes.sql"
                    ).read_text(encoding="utf-8-sig")
                )
            cls.demo = seed_demo(c)

    def setUp(self):
        import psycopg
        from psycopg.rows import dict_row

        self.c = psycopg.connect(self.dsn, row_factory=dict_row)
        self.c.execute("begin")
        self.event = self.demo["story"].id

    def tearDown(self):
        self.c.rollback()
        self.c.close()

    def test_search_snippet_is_never_analysis_body(self):
        from app.news.storage import save_article, export_batch

        a = normalize(
            NaverTests().item(originallink="https://unresolved.example.com/new"),
            "economy",
            [],
            is_demo=True,
        )
        save_article(self.c, a, query="x", raw={})
        batch = export_batch(self.c)
        self.assertEqual(batch.excluded["body_missing"], 1)
        self.assertNotIn(a.id, {v.article.id for v in batch.articles})

    def test_body_replay_cannot_restore_an_older_revision(self):
        from app.news.storage import save_body

        body = BodyImport.model_validate(self.demo["bodies"]["items"][0])
        old = save_body(self.c, body)
        new = save_body(
            self.c, body.model_copy(update={"text": body.text + " 새 본문."})
        )
        self.assertNotEqual(old, new)
        self.assertEqual(save_body(self.c, body), old)
        row = self.c.execute(
            "select current_body_id from private.news_v2_articles where id=%s",
            (body.article_id,),
        ).fetchone()
        self.assertEqual(row["current_body_id"], new)

    def test_storage_permission(self):
        from app.news.storage import save_body

        body = BodyImport.model_validate(self.demo["bodies"]["items"][0])
        body.rights.store = False
        with self.assertRaisesRegex(ValueError, "STORAGE_NOT_ALLOWED"):
            save_body(self.c, body)

    def test_stale_body_hides_publication_and_rejects_old_results(self):
        from app.news.storage import save_body
        from app.news.reader import publication
        from app.news.analysis import import_results

        body = BodyImport.model_validate(self.demo["bodies"]["items"][0])
        save_body(self.c, body.model_copy(update={"text": body.text + " 수정 내용."}))
        self.assertIsNone(publication(self.c, self.event))
        with self.assertRaisesRegex(ValueError, "STALE"):
            import_results(self.c, self.demo["results"])

    def test_input_hash_and_unknown_citations_are_rejected(self):
        from app.news.analysis import import_results

        batch = self.demo["results"].model_copy(deep=True)
        batch.input_hash = "wrong"
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
            import_results(self.c, batch)
        batch = self.demo["results"].model_copy(deep=True)
        batch.clusters[0].outputs[0].payload["bullets"][0]["article_ids"] = [
            str(uuid4())
        ]
        with self.assertRaisesRegex(ValueError, "CITATION"):
            import_results(self.c, batch)

    def test_duplicate_cluster_membership_is_rejected(self):
        from app.news.analysis import import_results

        batch = self.demo["results"].model_copy(deep=True)
        batch.clusters.append(
            batch.clusters[0].model_copy(update={"event_key": "duplicate"})
        )
        with self.assertRaisesRegex(ValueError, "MEMBERSHIP"):
            import_results(self.c, batch)

    def test_unreviewed_mode_does_not_leak_payload(self):
        from app.news.reader import read_analysis

        self.c.execute(
            "update private.news_v2_analyses set review_status='pending' where event_id=%s and mode='five_w'",
            (self.event,),
        )
        value = read_analysis(self.c, self.event, "five_w")
        self.assertEqual(value.status, "pending")
        self.assertIsNone(value.payload)

    def test_full_text_is_returned_only_with_display_permission(self):
        from app.news.reader import read_content

        bodies = self.demo["bodies"]["items"]
        allowed = read_content(self.c, self.event, bodies[0]["article_id"])
        denied = read_content(self.c, self.event, bodies[1]["article_id"])
        self.assertEqual(allowed.status, "available")
        self.assertTrue(allowed.text)
        self.assertEqual(denied.status, "link_only")
        self.assertIsNone(denied.text)
        self.assertIsNone(read_content(self.c, self.event, str(uuid4())))

    def test_sentiment_does_not_publish_private_quotes(self):
        from app.news.reader import read_analysis

        value = read_analysis(self.c, self.event, "sentiment")
        denied = self.demo["bodies"]["items"][1]["article_id"]
        row = next(
            r for r in value.payload["observations"] if r["article_id"] == denied
        )
        self.assertEqual(row["evidence"], "원문 인용문은 언론사 원문에서 확인해주세요.")

    def test_independent_publishers_and_explicit_review(self):
        from app.news.analysis import publish

        with self.assertRaisesRegex(ValueError, "EXPLICIT_REVIEW"):
            publish(self.c, self.event, reviewed=False)
        self.c.execute(
            "update private.news_v2_run_inputs set article_snapshot=jsonb_set(article_snapshot,'{publisher,group_id}','\"one-group\"') where run_id=%s",
            (self.demo["batch"].run_id,),
        )
        with self.assertRaisesRegex(ValueError, "TWO_INDEPENDENT"):
            publish(self.c, self.event, reviewed=True)

    def test_korean_event_date_uses_earliest_article_not_utc_day(self):
        from app.news.reader import publication

        row = publication(self.c, self.event)
        self.assertEqual(row["event_date"].isoformat(), "2026-10-22")
        first = min(
            datetime.fromisoformat(a["published_at"]).astimezone(timezone.utc)
            for a in row["story"]["articles"]
        )
        self.assertEqual(first.date().isoformat(), "2026-10-21")

    def test_anonymous_has_no_private_table_access(self):
        with self.c.transaction():
            self.c.execute("set local role anon")
            with self.assertRaises(Exception):
                with self.c.transaction():
                    self.c.execute("select text from private.news_v2_bodies")

    def test_real_api_date_filter_cors_modes_and_content(self):
        from app.news_api import app

        with patch.dict(os.environ, {"NEWS_DATABASE_URL": self.dsn}):
            with TestClient(app) as client:
                feed = client.get(
                    "/api/v2/stories?date=2026-10-22",
                    headers={"Origin": "http://127.0.0.1:5173"},
                )
                self.assertEqual(feed.status_code, 200, feed.text)
                self.assertEqual(feed.json()["total"], 1)
                self.assertEqual(
                    feed.headers["X-Request-ID"], feed.json()["meta"]["request_id"]
                )
                self.assertEqual(
                    feed.headers["Access-Control-Allow-Origin"], "http://127.0.0.1:5173"
                )
                self.assertEqual(
                    client.get("/api/v2/stories?date=2026-10-21").json()["total"], 0
                )
                self.assertEqual(
                    client.get("/api/v2/stories?date=bad").status_code, 422
                )
                self.assertEqual(
                    client.get(
                        "/api/v2/stories?from=2026-10-23&to=2026-10-22"
                    ).status_code,
                    422,
                )
                for mode in ("summary", "five_w", "easy", "sentiment"):
                    response = client.get(
                        f"/api/v2/stories/{self.event}/analyses/{mode}"
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["status"], "ready")
                self.assertEqual(client.get("/api/v2/stories/missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
