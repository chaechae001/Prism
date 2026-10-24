"""Input failures must be inspectable without DB access or source-content leakage."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.services.analyst_validation import (
    check_batch, read_checked_batch, plan_import, InvalidAnalystBatch,
)
from backend.app.services.body_import import import_bodies
from backend.app.worker import main

EXAMPLE = Path(__file__).resolve().parents[2] / "contracts/analyst-batch.example.json"


class AnalystValidationTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def codes(self, checked):
        return {x["code"] for x in checked.report["errors"]}

    def test_valid_batch_is_offline_and_never_writes(self):
        with patch("backend.app.services.analyst_validation.get_engine") as db:
            result = check_batch(self.payload)
        db.assert_not_called()
        self.assertTrue(result.report["valid"])
        self.assertFalse(result.report["written"])
        self.assertFalse(result.report["database_checked"])

    def test_hash_is_of_exact_utf8_body(self):
        self.payload["articles"][0]["text"] += "\n"
        self.assertIn("HASH_MISMATCH", self.codes(check_batch(self.payload)))

    def test_blank_required_strings_are_rejected(self):
        for field in ("id", "title", "publisher_id", "publisher_group_id", "text"):
            with self.subTest(field=field):
                payload = copy.deepcopy(self.payload)
                payload["articles"][0][field] = " \n "
                self.assertIn("BLANK_FIELD", self.codes(check_batch(payload)))

    def test_duplicate_ids_are_rejected(self):
        a = copy.deepcopy(self.payload["articles"][0])
        a["canonical_url"] = "https://example.com/another"
        self.payload["articles"].append(a)
        self.assertIn("DUPLICATE_ID", self.codes(check_batch(self.payload)))

    def test_duplicate_urls_are_rejected_before_import(self):
        a = copy.deepcopy(self.payload["articles"][0])
        a["id"] = "another-id"
        self.payload["articles"].append(a)
        checked = check_batch(self.payload)
        self.assertIn("DUPLICATE_URL", self.codes(checked))
        with patch("backend.app.services.body_import.get_engine") as db:
            with self.assertRaises(InvalidAnalystBatch):
                import_bodies(checked.batch)
        db.assert_not_called()

    def test_same_body_across_distinct_sources_warns_without_dropping(self):
        a = copy.deepcopy(self.payload["articles"][0])
        a.update(id="other-id", canonical_url="https://example.com/other", publisher_id="other-publisher")
        self.payload["articles"].append(a)
        checked = check_batch(self.payload)
        self.assertTrue(checked.report["valid"])
        self.assertEqual(checked.report["article_count"], 2)
        self.assertIn("DUPLICATE_BODY", {x["code"] for x in checked.report["warnings"]})

    def test_storage_permission_does_not_imply_summary_permission(self):
        self.payload["articles"][0]["allowed_uses"] = ["collect", "store"]
        checked = check_batch(self.payload)
        self.assertTrue(checked.report["valid"])
        self.assertEqual(checked.report["warnings"][0]["code"], "SUMMARY_NOT_ALLOWED")

    def test_unknown_or_denied_storage_is_blocked(self):
        for license_status in ("unknown", "denied"):
            self.payload["articles"][0]["license_status"] = license_status
            self.assertIn("STORAGE_NOT_ALLOWED", self.codes(check_batch(self.payload)))

    def test_collected_before_published_is_reported(self):
        self.payload["articles"][0]["collected_at"] = "2026-10-20T09:00:00+09:00"
        self.assertIn("INVALID_TIME_ORDER", self.codes(check_batch(self.payload)))

    def test_timezone_is_required(self):
        self.payload["articles"][0]["published_at"] = "2026-10-21T09:00:00"
        self.assertIn("INVALID_STRUCTURE", self.codes(check_batch(self.payload)))

    def test_credentials_in_url_are_rejected(self):
        self.payload["articles"][0]["canonical_url"] = "https://unit:secret@example.com/article"
        checked = check_batch(self.payload)
        self.assertIn("URL_CREDENTIALS", self.codes(checked))
        self.assertNotIn("unit:secret", json.dumps(checked.report))

    def test_structural_errors_do_not_echo_private_body_or_unknown_keys(self):
        self.payload["articles"][0]["text"] = {"PRIVATE_BODY_SENTINEL": "hidden"}
        self.payload["PRIVATE_FIELD_SENTINEL"] = "hidden"
        checked = check_batch(self.payload)
        report = json.dumps(checked.report)
        self.assertFalse(checked.report["valid"])
        self.assertNotIn("SENTINEL", report)
        self.assertNotIn("hidden", report)

    def test_batch_limit_applies_to_model_instances_too(self):
        batch = check_batch(self.payload).batch
        with patch("backend.app.services.analyst_validation.MAX_ARTICLES", 0):
            self.assertFalse(check_batch(batch).report["valid"])

    def test_missing_batch_id_is_not_echoed(self):
        self.payload["batch_id"] = "  "
        self.assertIn("EMPTY_BATCH_ID", self.codes(check_batch(self.payload)))

    def test_large_body_is_rejected(self):
        with patch("backend.app.services.analyst_validation.MAX_BODY_CHARS", 1):
            self.assertIn("BODY_TOO_LARGE", self.codes(check_batch(self.payload)))

    def test_bom_encoded_json_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batch.json"
            path.write_text(json.dumps(self.payload), encoding="utf-8-sig")
            self.assertTrue(read_checked_batch(path).report["valid"])

    def test_file_errors_are_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "PRIVATE_PATH_SENTINEL.json"
            path.write_text('{"PRIVATE_BODY_SENTINEL":', encoding="utf-8")
            report = read_checked_batch(path).report
            self.assertFalse(report["valid"])
            self.assertNotIn("SENTINEL", json.dumps(report))

    def test_file_limit_is_bounded(self):
        with patch("backend.app.services.analyst_validation.MAX_FILE_BYTES", 1):
            self.assertEqual(read_checked_batch(EXAMPLE).report["errors"][0]["code"], "FILE_TOO_LARGE")

    def test_invalid_plan_never_connects_to_database(self):
        with patch("backend.app.services.analyst_validation.get_engine") as db:
            report = plan_import(check_batch({}))
        db.assert_not_called()
        self.assertFalse(report["database_checked"])

    def test_plan_reports_missing_and_mismatched_sources_without_content(self):
        second = copy.deepcopy(self.payload["articles"][0])
        second.update(id="second", canonical_url="https://example.com/second")
        self.payload["articles"].append(second)
        engine = MagicMock()
        connection = engine.connect.return_value.__enter__.return_value
        connection.execute.return_value.mappings.return_value.all.return_value = [
            {"id": "db-id", "canonical_url": str(check_batch(self.payload).batch.articles[0].canonical_url), "publisher_id": "wrong-publisher"}
        ]
        report = plan_import(check_batch(self.payload), engine=engine)
        self.assertEqual(str(connection.execute.call_args_list[0].args[0]), "SET TRANSACTION READ ONLY")
        self.assertFalse(report["ready_for_import"])
        self.assertEqual(report["mapping"]["publisher_mismatch_indices"], [0])
        self.assertEqual(report["mapping"]["missing_article_indices"], [1])
        self.assertFalse(report["written"])
        self.assertNotIn("db-id", json.dumps(report))

    def test_cli_offline_is_json_and_does_not_connect(self):
        output = io.StringIO()
        with patch("backend.app.worker.load_environment"), patch("backend.app.services.analyst_validation.get_engine") as db, redirect_stdout(output):
            result = main(["validate-batch", "--input", str(EXAMPLE)])
        self.assertEqual(result, 0)
        self.assertTrue(json.loads(output.getvalue())["valid"])
        db.assert_not_called()

    def test_cli_invalid_import_never_opens_database(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{}", encoding="utf-8")
            with patch("backend.app.worker.load_environment"), patch("backend.app.services.body_import.get_engine") as db, redirect_stdout(output):
                result = main(["import-bodies", "--input", str(path)])
        self.assertEqual(result, 1)
        db.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())["valid"])
