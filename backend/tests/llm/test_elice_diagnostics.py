"""400 오류의 알려진 분류만 표시하고 키·본문·서버 원문을 숨기는지 확인합니다."""

import io
import json
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from backend.app.llm.elice_client import EliceClient, redacted_error_detail, safe_error_hint
from backend.app.llm.elice_settings import EliceSettings
from backend.app.llm.elice_cli import main
from backend.app.llm.summarizer import LLMSummaryError


class DiagnosticsTests(unittest.TestCase):
    def test_cli_diagnostic_displays_relation_without_key_or_body(self):
        settings = EliceSettings(api_url="https://example.test/v1/chat/completions", api_key="private-test-key")
        opener = Mock()
        body = json.dumps({"error": {"message": "max_completion_tokens cannot be combined with stream. private-test-key private-body"}}).encode()
        opener.open.side_effect = HTTPError(settings.api_url, 400, "private", {}, io.BytesIO(body))
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "article.json"
            source.write_text(json.dumps({"id": "demo", "title": "demo", "text": "private-body", "is_demo": True}), encoding="utf-8")
            with patch("backend.app.llm.elice_cli.EliceSettings.from_env", return_value=settings):
                with patch("backend.app.llm.elice_client.build_opener", return_value=opener):
                    with patch("sys.argv", ["elice", "summarize", "--input", str(source), "--diagnostic"]):
                        log = io.StringIO()
                        with contextlib.redirect_stdout(log), self.assertRaises(SystemExit) as caught:
                            main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("cannot be combined with stream", log.getvalue())
        self.assertNotIn("private-test-key", log.getvalue())
        self.assertNotIn("private-body", log.getvalue())
        opener.open.assert_called_once()

    def test_detailed_parameter_relation_is_retained(self):
        raw = json.dumps({"error": {"message": "max_completion_tokens cannot be combined with stream."}}).encode()
        detail = redacted_error_detail(raw, api_key="test-key")
        self.assertEqual(detail, "max_completion_tokens cannot be combined with stream.")

    def test_detail_removes_actual_key_and_input_values(self):
        article = {"id": "private-id", "title": "민감한 제목", "text": "민감한 기사 본문"}
        raw = json.dumps({"error": {"message": "Invalid input 민감한 기사 본문, key=test-secret; '민감한 제목' private-id"}}, ensure_ascii=False).encode()
        detail = redacted_error_detail(raw, api_key="test-secret", payload={"messages": [
            {"role": "user", "content": json.dumps(article, ensure_ascii=False)}]})
        for private in ("test-secret", *article.values()):
            self.assertNotIn(private, detail)

    def test_detail_masks_unrelated_quoted_data_bearer_and_urls(self):
        raw = json.dumps({"error": {"message": "Invalid 'private words', 'stream'; Bearer abc123; https://example.test/path?key=other"}}).encode()
        detail = redacted_error_detail(raw, api_key="actual-test-key")
        self.assertNotIn("private words", detail)
        self.assertNotIn("abc123", detail)
        self.assertNotIn("example.test", detail)
        self.assertIn("'stream'", detail)

    def test_detail_ignores_request_and_header_fields(self):
        raw = b'{"error":{"message":"Bad request","headers":{"Authorization":"private"},"input":"private"}}'
        self.assertEqual(redacted_error_detail(raw, api_key="actual-test-key"), "Bad request")

    def test_detail_bounds_size_and_rejects_non_messages(self):
        raw = json.dumps({"error": {"message": "short words " * 200}}).encode()
        self.assertLessEqual(len(redacted_error_detail(raw, api_key="test-key")), 700)
        self.assertNotIn("private", redacted_error_detail(b'{"detail":"private"}', api_key="test-key"))

    def test_unsupported_option_classified_without_echoing_provider_message(self):
        raw = json.dumps({"error": {"code": "unsupported_parameter", "param": "reasoning_effort",
            "message": "Unsupported parameter: reasoning_effort; 민감한 본문; secret-test-key"}}).encode()
        hint = safe_error_hint(raw)
        self.assertIn("UNSUPPORTED_PARAMETER", hint)
        self.assertIn("reasoning_effort", hint)
        self.assertNotIn("민감한", hint)
        self.assertNotIn("secret-test-key", hint)

    def test_invalid_schema_classified(self):
        hint = safe_error_hint(b'{"error":{"code":"invalid_json_schema","param":"response_format"}}')
        self.assertIn("JSON_SCHEMA_INVALID", hint)
        self.assertIn("response_format", hint)

    def test_bento_validation_error_classified(self):
        hint = safe_error_hint(b'{"detail":[{"type":"extra_forbidden","loc":["body","reasoning_effort"],"input":"secret"}]}')
        self.assertIn("UNSUPPORTED_PARAMETER", hint)
        self.assertIn("reasoning_effort", hint)
        self.assertNotIn("secret", hint)

    def test_unknown_and_non_json_errors_do_not_echo_content(self):
        for raw in (b"<html>private</html>", b"[]", b'{"unexpected":"private"}', b"\xff"):
            hint = safe_error_hint(raw)
            self.assertNotIn("private", hint)
            self.assertNotIn("unexpected", hint)

    def test_http_400_contains_safe_hint_and_is_not_retried(self):
        client = EliceClient(EliceSettings(api_url="https://example.test/v1/chat/completions", api_key="test-secret"))
        client._opener = Mock()
        body = b'{"error":{"code":"unsupported_value","param":"response_format","message":"private test-secret"}}'
        client._opener.open.side_effect = HTTPError("https://example.test", 400, "private", {}, io.BytesIO(body))
        with self.assertRaises(LLMSummaryError) as error:
            client.generate("system", "article")
        self.assertEqual(error.exception.code, "MODEL_BAD_REQUEST")
        self.assertIn("UNSUPPORTED_VALUE", str(error.exception))
        self.assertNotIn("test-secret", str(error.exception))
        self.assertNotIn("private", str(error.exception))
        client._opener.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
