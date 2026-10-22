import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.connection_api import app, get_snapshot
from app.connection_repository import ROOT, Snapshot, load_snapshot
from app.rss_preview import RssRecord, plain_text, rss_to_story


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        app.dependency_overrides[get_snapshot] = lambda: load_snapshot("fixture")

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_frontend_default_request(self):
        r = self.client.get("/api/v1/stories?q=&mode=balanced&diversity=70&limit=6")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 12)
        self.assertEqual(len(r.json()["items"]), 6)
        self.assertEqual(r.headers["X-Request-ID"], r.json()["meta"]["request_id"])

    def test_filter_and_cursor_query_binding(self):
        r = self.client.get("/api/v1/stories?q=AI&category=technology").json()
        self.assertEqual([i["story"]["id"] for i in r["items"]], ["story-001"])
        cursor = self.client.get("/api/v1/stories?limit=3").json()["next_cursor"]
        second = self.client.get("/api/v1/stories", params={"limit": 3, "cursor": cursor})
        self.assertEqual(second.status_code, 200)
        changed = self.client.get("/api/v1/stories", params={"q": "AI", "cursor": cursor})
        self.assertEqual(changed.status_code, 422)

    def test_cursor_rejected_after_snapshot_change(self):
        cursor = self.client.get("/api/v1/stories?limit=3").json()["next_cursor"]
        snapshot = load_snapshot("fixture")
        snapshot.version = "changed-dataset"
        app.dependency_overrides[get_snapshot] = lambda: snapshot
        self.assertEqual(self.client.get("/api/v1/stories", params={"cursor": cursor}).status_code, 422)

    def test_cors_preflight_and_request_id_visibility(self):
        headers = {"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-mock-scenario"}
        response = self.client.options("/api/v1/stories", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], headers["Origin"])
        headers["Origin"] = "https://unapproved.example"
        self.assertEqual(self.client.options("/api/v1/stories", headers=headers).status_code, 400)

    def test_categories_detail_and_nonpersisted_feedback(self):
        self.assertEqual(sum(x["count"] for x in self.client.get("/api/v1/categories").json()["items"]), 12)
        self.assertEqual(self.client.get("/api/v1/stories/story-001").json()["story"]["coverage"]["article_count"], 3)
        self.assertEqual(self.client.get("/api/v1/stories/missing").status_code, 404)
        r = self.client.post("/api/v1/feedback", json={"story_id": "story-001", "kind": "useful"})
        self.assertEqual(r.status_code, 201)
        self.assertIs(r.json()["persisted"], False)

    def test_unexpected_failure_is_json_without_secret(self):
        def fail():
            raise RuntimeError("password=DO_NOT_EXPOSE")
        app.dependency_overrides[get_snapshot] = fail
        with self.assertLogs("prism.connection", level="ERROR") as logs:
            r = self.client.get("/api/v1/stories", headers={"Origin": "http://127.0.0.1:5173"})
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json()["error"]["request_id"], r.headers["X-Request-ID"])
        self.assertEqual(r.headers["access-control-allow-origin"], "http://127.0.0.1:5173")
        self.assertNotIn("DO_NOT_EXPOSE", r.text + " ".join(logs.output))

    def test_rss_preview_metadata_and_no_fake_ai(self):
        app.dependency_overrides[get_snapshot] = lambda: load_snapshot("rss-fixture")
        r = self.client.get("/api/v1/stories").json()
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["meta"]["policy_version"], "rss-preview-v1")
        story = r["items"][0]["story"]
        self.assertEqual(story["summary"]["status"], "pending")
        self.assertEqual(story["summary"]["bullets"], [])
        self.assertEqual(story["perspectives"], [])
        self.assertEqual(story["coverage"]["publisher_count"], 1)

    def test_parameter_validation(self):
        for path in ["/api/v1/stories?limit=0", "/api/v1/stories?limit=1.5", "/api/v1/stories?category=bad", "/api/v1/stories?diversity=101"]:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 422)
            self.assertIn("error", r.json())


class RssAdapterTests(unittest.TestCase):
    def setUp(self):
        self.rows = json.loads((ROOT / "docs/architecture/rss-record-v1.examples.json").read_text(encoding="utf-8"))
        self.now = datetime(2026, 10, 23, tzinfo=timezone.utc)

    def test_missing_description_keeps_empty_summary(self):
        s, reason = rss_to_story(RssRecord.model_validate(self.rows[0]), self.now)
        self.assertIsNone(reason)
        self.assertEqual(s.summary.bullets, [])
        self.assertIsNone(s.summary.model_version)
        self.assertEqual(len(s.articles), 1)

    def test_missing_date_does_not_use_collection_date(self):
        s, reason = rss_to_story(RssRecord.model_validate(self.rows[1]), self.now)
        self.assertIsNone(s)
        self.assertEqual(reason, "missing_publication_date")

    def test_future_date_is_held(self):
        row = {**self.rows[0], "published_at": "2099-01-01T00:00:00Z"}
        self.assertEqual(rss_to_story(RssRecord.model_validate(row), self.now)[1], "future_publication_date")

    def test_unknown_publication_rights_are_held(self):
        row = copy.deepcopy(self.rows[0])
        row["rights"]["publish_summary"] = "unknown"
        self.assertEqual(rss_to_story(RssRecord.model_validate(row), self.now)[1], "publication_not_confirmed")

    def test_html_is_not_an_ai_summary_or_executable_markup(self):
        self.assertEqual(plain_text('<p>Hello &amp; world</p><script>evil()</script><style>hidden</style>'), 'Hello & world')
        row = {**self.rows[0], "rss_description": '<p>Provided text</p><script>evil()</script>'}
        s, _ = rss_to_story(RssRecord.model_validate(row), self.now)
        self.assertNotIn("evil", s.dek)
        self.assertEqual(s.summary.bullets, [])

    def test_cross_feed_duplicate_canonical_url_has_one_preview(self):
        duplicate = {**self.rows[0], "id": "different-intake", "feed_id": "other-feed"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.json"
            path.write_text(json.dumps([self.rows[0], duplicate]), encoding="utf-8")
            with patch.dict(os.environ, {"RSS_FIXTURE_PATH": str(path)}):
                self.assertEqual(len(load_snapshot("rss-fixture").stories), 1)

    def test_db_failure_never_falls_back_to_fixture(self):
        with patch("app.connection_repository.importlib.import_module", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                load_snapshot("db-demo")

    def test_live_reader_must_return_list(self):
        class Reader:
            def list_rss_records(self, limit):
                return {"items": []}
        with patch("app.connection_repository.importlib.import_module", return_value=Reader()):
            with self.assertRaises(TypeError):
                load_snapshot("rss-reader")


if __name__ == "__main__":
    unittest.main()
