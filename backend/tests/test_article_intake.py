"""Local intake CLI must default to a non-writing plan and sanitize failures."""
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.services.analyst_validation import check_batch, InvalidAnalystBatch
from backend.app.services.article_intake import intake_articles, IntakeConflict
from backend.app.worker import main

EXAMPLE = Path(__file__).resolve().parents[2] / "contracts/analyst-batch.example.json"


class ArticleIntakeTests(unittest.TestCase):
    def setUp(self):
        self.batch = check_batch(json.loads(EXAMPLE.read_text(encoding="utf-8"))).batch
        self.engine = MagicMock()
        self.connection = self.engine.connect.return_value.__enter__.return_value

    def test_default_plan_is_read_only_and_reports_unknown_publisher(self):
        self.connection.execute.return_value.mappings.return_value.all.return_value = []
        with patch("backend.app.services.article_intake._store_bodies") as store:
            report = intake_articles(self.batch, engine=self.engine)
        self.assertEqual(str(self.connection.execute.call_args_list[0].args[0]), "SET TRANSACTION READ ONLY")
        self.engine.begin.assert_not_called()
        store.assert_not_called()
        self.assertFalse(report["ready_for_intake"])
        self.assertFalse(report["written"])
        self.assertEqual(report["intake_errors"][0]["code"], "UNKNOWN_PUBLISHER")

    def test_invalid_input_is_rejected_without_a_database_connection(self):
        bad = self.batch.model_copy(update={"batch_id": " "})
        with patch("backend.app.services.article_intake.get_engine") as db:
            with self.assertRaises(InvalidAnalystBatch):
                intake_articles(bad)
        db.assert_not_called()

    def test_cli_passes_apply_false_by_default(self):
        report = {"ready_for_intake": True, "written": False}
        with patch("backend.app.worker.load_environment"), patch("backend.app.services.article_intake.intake_articles", return_value=report) as intake, redirect_stdout(io.StringIO()):
            self.assertEqual(main(["intake-articles", "--input", str(EXAMPLE)]), 0)
        self.assertFalse(intake.call_args.kwargs["apply"])
        self.assertFalse(intake.call_args.kwargs["is_demo"])

    def test_cli_requires_explicit_apply_and_demo_flags(self):
        report = {"ready_for_intake": True, "written": True}
        with patch("backend.app.worker.load_environment"), patch("backend.app.services.article_intake.intake_articles", return_value=report) as intake, redirect_stdout(io.StringIO()):
            self.assertEqual(main(["intake-articles", "--input", str(EXAMPLE), "--apply", "--demo"]), 0)
        self.assertTrue(intake.call_args.kwargs["apply"])
        self.assertTrue(intake.call_args.kwargs["is_demo"])

    def test_cli_conflicts_have_no_source_values(self):
        report = {"ready_for_intake": False, "written": False, "intake_errors": [{"code": "UNKNOWN_PUBLISHER", "article_index": 0}]}
        output = io.StringIO()
        with patch("backend.app.worker.load_environment"), patch("backend.app.services.article_intake.intake_articles", side_effect=IntakeConflict(report)), redirect_stdout(output):
            self.assertEqual(main(["intake-articles", "--input", str(EXAMPLE), "--apply"]), 1)
        self.assertEqual(json.loads(output.getvalue()), report)
        self.assertNotIn(self.batch.articles[0].text, output.getvalue())

    def test_cli_database_failure_does_not_echo_exception(self):
        output = io.StringIO()
        with patch("backend.app.worker.load_environment"), patch("backend.app.services.article_intake.intake_articles", side_effect=RuntimeError("PRIVATE_CONNECTION_SENTINEL")), redirect_stdout(output):
            self.assertEqual(main(["intake-articles", "--input", str(EXAMPLE)]), 1)
        self.assertNotIn("PRIVATE_CONNECTION_SENTINEL", output.getvalue())

    def test_cli_bad_file_never_calls_intake(self):
        with patch("backend.app.worker.load_environment"), patch("backend.app.services.article_intake.intake_articles") as intake, redirect_stdout(io.StringIO()):
            self.assertEqual(main(["intake-articles", "--input", "missing-local-input.json"]), 1)
        intake.assert_not_called()
