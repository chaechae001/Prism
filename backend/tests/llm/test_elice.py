"""실제 키·네트워크·크레딧 없이 엘리스 연결 및 결과 검증을 시험합니다."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from backend.app.llm.elice_client import EliceClient, summarize_with_elice
from backend.app.llm.elice_cli import main
from backend.app.llm.elice_settings import EliceSettings
from backend.app.llm.schemas import ArticleBody
from backend.app.llm.summarizer import LLMSummaryError, summarize_article


TEST_URL = "https://example.test/project-id/v1/chat/completions"
TEST_KEY = "fake-test-key-not-a-real-credential"


def draft():
    return {"title": "가상 기사 요약", "bullets": [{"text": "도서관 운영을 시범 확대한다.",
            "article_ids": ["demo-001"]}], "perspectives": [], "unknowns": []}


def response(**overrides):
    return {"model": "gpt-5-mini-2025-08-07", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(draft())}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}, **overrides}


class EliceTests(unittest.TestCase):
    def setUp(self):
        self.settings = EliceSettings(api_url=TEST_URL, api_key=TEST_KEY)
        self.client = EliceClient(self.settings)
        self.opener = Mock()
        self.client._opener = self.opener
        self.article = ArticleBody(id="demo-001", title="가상 기사", text="가상 도서관 운영 기사입니다.", is_demo=True)

    def reply(self, data):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.opener.open.return_value = io.BytesIO(raw)

    def assert_error(self, code, function):
        with self.assertRaises(LLMSummaryError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(TEST_KEY, str(caught.exception))
        self.assertNotIn("민감한 원문", str(caught.exception))

    def test_request_has_auth_schema_and_gpt5_options(self):
        self.reply(response())
        self.client.generate("요약 지시", "기사 본문")
        request = self.opener.open.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, TEST_URL)
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TEST_KEY)
        self.assertEqual(body["model"], "gpt-5-mini")
        self.assertEqual(body["reasoning_effort"], "minimal")
        self.assertEqual(body["max_completion_tokens"], 2000)
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertFalse(body["stream"])
        for name in ("temperature", "top_p", "think", "options", "num_ctx", "max_tokens"):
            self.assertNotIn(name, body)
        self.assertEqual(self.opener.open.call_args.kwargs["timeout"], 120)
        self.assertEqual(self.client.last_usage["total_tokens"], 300)

    def test_check_gets_models_without_generation(self):
        self.reply({"data": [{"id": "openai/gpt-5-mini"}]})
        self.client.check()
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/project-id/v1/models")
        self.assertEqual(request.method, "GET")
        self.assertIsNone(request.data)
        self.opener.open.assert_called_once()

    def test_unavailable_model_and_invalid_model_list(self):
        for payload, code in (({"data": []}, "MODEL_NOT_FOUND"), ({"data": {}}, "INVALID_MODEL_OUTPUT")):
            self.reply(payload)
            self.assert_error(code, self.client.check)

    def test_http_errors_have_distinct_codes_and_no_raw_error_body(self):
        for status, code in ((400, "MODEL_BAD_REQUEST"), (401, "MODEL_AUTH_FAILED"),
                             (403, "MODEL_FORBIDDEN"), (404, "MODEL_ENDPOINT_NOT_FOUND"),
                             (429, "MODEL_RATE_LIMITED"), (500, "MODEL_HTTP_ERROR"), (302, "MODEL_HTTP_ERROR")):
            with self.subTest(status=status):
                self.opener.open.side_effect = HTTPError(TEST_URL, status, TEST_KEY, {}, io.BytesIO(b"private"))
                self.assert_error(code, lambda: self.client.generate("s", "u"))

    def test_timeout_direct_and_wrapped(self):
        for error in (TimeoutError(TEST_KEY), URLError(TimeoutError(TEST_KEY))):
            self.opener.open.side_effect = error
            self.assert_error("MODEL_TIMEOUT", lambda: self.client.generate("s", "u"))

    def test_connection_failure_is_sanitized(self):
        self.opener.open.side_effect = URLError("민감한 원문 " + TEST_KEY)
        self.assert_error("MODEL_UNAVAILABLE", lambda: self.client.generate("s", "u"))

    def test_invalid_json_and_server_error_envelope_rejected(self):
        for raw in (b"invalid", b"\xff", b"[]", {"error": {"message": TEST_KEY}}):
            self.reply(raw)
            self.assert_error("INVALID_MODEL_OUTPUT", lambda: self.client.generate("s", "u"))

    def test_response_size_limit(self):
        self.reply(b"x" * (1024 * 1024 + 1))
        self.assert_error("INVALID_MODEL_OUTPUT", lambda: self.client.generate("s", "u"))

    def test_missing_choices_or_message_rejected(self):
        for payload in ({"choices": []}, {"choices": "wrong"}, {"choices": [{}]}):
            self.reply(payload)
            self.assert_error("INVALID_MODEL_OUTPUT", lambda: self.client.generate("s", "u"))

    def test_refusal_and_content_filter_rejected(self):
        for choice in ({"finish_reason": "stop", "message": {"refusal": "테스트 거절 응답"}},
                       {"finish_reason": "content_filter", "message": {}}):
            self.reply(response(choices=[choice]))
            self.assert_error("MODEL_REFUSED", lambda: self.client.generate("s", "u"))

    def test_length_stop_rejected_even_when_json_is_valid(self):
        data = response()
        data["choices"][0]["finish_reason"] = "length"
        self.reply(data)
        self.assert_error("MODEL_INCOMPLETE", lambda: self.client.generate("s", "u"))

    def test_empty_non_text_and_wrong_role_rejected(self):
        for message in ({"role": "assistant", "content": " "}, {"role": "assistant", "content": None},
                        {"role": "user", "content": "text"}):
            self.reply(response(choices=[{"finish_reason": "stop", "message": message}]))
            self.assert_error("INVALID_MODEL_OUTPUT", lambda: self.client.generate("s", "u"))

    def test_provider_error_survives_summary_layer(self):
        self.opener.open.side_effect = HTTPError(TEST_URL, 401, TEST_KEY, {}, io.BytesIO())
        self.assert_error("MODEL_AUTH_FAILED", lambda: summarize_article(self.article,
            generate=self.client.generate, model_version="gpt-5-mini", is_mock=False))

    def test_service_records_model_snapshot_and_keeps_pending_demo(self):
        self.reply(response())
        with patch("backend.app.llm.elice_client.EliceClient", return_value=self.client):
            result = summarize_with_elice(self.article, self.settings)
        self.assertEqual(result.model_version, "gpt-5-mini-2025-08-07")
        self.assertEqual(result.status, "pending")
        self.assertFalse(result.is_mock)
        self.assertTrue(result.is_demo)

    def test_extra_fields_and_wrong_article_id_rejected_after_model_response(self):
        for changes, code in (({"status": "ready"}, "INVALID_MODEL_OUTPUT"),
                              ({"bullets": [{"text": "문장", "article_ids": ["other"]}]}, "INVALID_CITATION")):
            content = {**draft(), **changes}
            self.reply(response(choices=[{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(content)}}]))
            self.assert_error(code, lambda: summarize_article(self.article,
                generate=self.client.generate, model_version="gpt-5-mini", is_mock=False))

    def test_invalid_input_rejected_before_client_creation(self):
        with patch("backend.app.llm.elice_client.EliceClient") as constructor:
            with self.assertRaises(TypeError):
                summarize_with_elice({"text": "본문"}, self.settings)
            constructor.assert_not_called()


class SettingsTests(unittest.TestCase):
    def test_non_stream_proxy_limit_rejected_before_api_call(self):
        EliceSettings(api_url=TEST_URL, api_key=TEST_KEY, max_completion_tokens=2000)
        for value in (2001, 4096):
            with self.subTest(value=value), self.assertRaises(ValueError):
                EliceSettings(api_url=TEST_URL, api_key=TEST_KEY, max_completion_tokens=value)

    def test_key_is_not_in_settings_repr(self):
        settings = EliceSettings(api_url=TEST_URL, api_key=TEST_KEY)
        self.assertNotIn(TEST_KEY, repr(settings))

    def test_invalid_settings_rejected(self):
        for changes in ({"api_url": "http://example.test/v1/chat/completions"},
                        {"api_url": "https://example.test/base"}, {"api_url": TEST_URL + "?key=x"},
                        {"api_key": ""}, {"api_key": "REPLACE_WITH_YOUR_KEY"}, {"api_key": "key\nvalue"},
                        {"model": "qwen3.5:9b"}, {"timeout_seconds": float("nan")},
                        {"max_completion_tokens": 100}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                EliceSettings(**{"api_url": TEST_URL, "api_key": TEST_KEY, **changes})

    def test_env_loading_does_not_require_database_or_openai_key(self):
        with patch.dict(os.environ, {"ELICE_API_URL": TEST_URL, "ELICE_API_KEY": TEST_KEY}, clear=True):
            with patch("backend.app.llm.elice_settings.load_dotenv") as loader, patch("backend.app.llm.elice_settings.load_environment"):
                settings = EliceSettings.from_env()
        self.assertEqual(settings.model, "gpt-5-mini")
        self.assertEqual(loader.call_args.args[0].parent, Path(__file__).resolve().parents[3])


class CLITests(unittest.TestCase):
    def test_cli_saves_valid_result_and_does_not_print_key(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps(response()).encode())
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "input.json", Path(folder) / "output.json"
            source.write_text(json.dumps({"id": "demo-001", "title": "가상 기사", "text": "가상 본문", "is_demo": True}), encoding="utf-8")
            settings = EliceSettings(api_url=TEST_URL, api_key=TEST_KEY)
            with patch("backend.app.llm.elice_cli.EliceSettings.from_env", return_value=settings):
                with patch("backend.app.llm.elice_client.build_opener", return_value=opener):
                    with patch("sys.argv", ["elice", "summarize", "--input", str(source), "--output", str(target)]):
                        log = io.StringIO()
                        with contextlib.redirect_stdout(log):
                            main()
            result = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(result["article_id"], "demo-001")
            self.assertEqual(result["model_version"], "gpt-5-mini-2025-08-07")
            self.assertNotIn(TEST_KEY, log.getvalue())
            self.assertFalse(result["is_mock"])
            opener.open.assert_called_once()

    def test_invalid_article_does_not_call_model(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "bad.json"
            source.write_text('{"id":"a","title":"title","text":" "}', encoding="utf-8")
            with patch("backend.app.llm.elice_cli.EliceSettings.from_env", return_value=EliceSettings(api_url=TEST_URL, api_key=TEST_KEY)):
                with patch("backend.app.llm.elice_cli.EliceClient") as constructor:
                    with patch("sys.argv", ["elice", "summarize", "--input", str(source)]):
                        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit_info:
                            main()
                        self.assertEqual(exit_info.exception.code, 1)
                        constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
