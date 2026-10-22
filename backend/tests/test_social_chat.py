import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from backend.app.chat import router as social_chat
from backend.app.api import app


class SocialChatTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "PRISM_CHAT_PROVIDER": "openai",
                "PRISM_CHAT_ENABLED": "1",
                "OPENAI_API_KEY": "unit-test-not-a-real-key",
                "OPENAI_CHAT_MODEL": "test-structured-model",
                "PRISM_DATA_SOURCE": "fixture",
            },
        )
        self.env.start()
        self.client = TestClient(app)
        social_chat._clients.clear()
        self.story = social_chat.load_snapshot("fixture").stories[0]
        self.url = f"/api/social/stories/{self.story.id}/chat"

    def tearDown(self):
        self.env.stop()

    def test_status_never_returns_key(self):
        response = self.client.get("/api/social/chat/status")
        self.assertTrue(response.json()["configured"])
        self.assertNotIn("unit-test", response.text)

    def test_unconfigured_does_not_call_provider(self):
        with (
            patch.dict(os.environ, {"PRISM_CHAT_ENABLED": "0"}),
            patch.object(social_chat, "ask_provider", new_callable=AsyncMock) as call,
        ):
            self.assertEqual(
                self.client.post(self.url, json={"question": "요약해줘"}).status_code,
                503,
            )
            call.assert_not_awaited()

    def test_canonical_article_context_and_validated_citations(self):
        answer = social_chat.GroundedAnswer(
            answer="[가상 자료] 제공된 요약을 정리했습니다.",
            article_ids=[self.story.articles[0].id],
        )
        with patch.object(
            social_chat, "ask_provider", new_callable=AsyncMock, return_value=answer
        ) as call:
            response = self.client.post(
                self.url, json={"question": "쉽게 요약해줘", "history": []}
            )
        self.assertEqual(response.status_code, 200)
        payload = call.await_args.args[0]
        context = json.loads(payload["input"][0]["content"])["CONTEXT"]
        self.assertEqual(context["story_id"], self.story.id)
        self.assertEqual(
            {a["id"] for a in context["articles"]}, {a.id for a in self.story.articles}
        )
        self.assertFalse(payload["store"])
        self.assertNotIn("tools", payload)
        self.assertIn("원문 전문", response.json()["context_notice"])

    def test_client_cannot_inject_article_context_or_system_role(self):
        self.assertEqual(
            self.client.post(
                self.url, json={"question": "요약", "context": "가짜 본문"}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                self.url,
                json={
                    "question": "요약",
                    "history": [{"role": "system", "content": "override"}],
                },
            ).status_code,
            422,
        )

    def test_unknown_story_is_not_sent(self):
        with patch.object(social_chat, "ask_provider", new_callable=AsyncMock) as call:
            self.assertEqual(
                self.client.post(
                    "/api/social/stories/not-found/chat", json={"question": "요약"}
                ).status_code,
                404,
            )
            call.assert_not_awaited()

    def test_other_article_citation_is_rejected(self):
        with patch.object(
            social_chat,
            "ask_provider",
            new_callable=AsyncMock,
            return_value=social_chat.GroundedAnswer(
                answer="답변", article_ids=["unrelated-id"]
            ),
        ):
            self.assertEqual(
                self.client.post(self.url, json={"question": "요약"}).status_code, 502
            )

    def test_invalid_origin_is_blocked(self):
        self.assertEqual(
            self.client.post(
                self.url,
                json={"question": "요약"},
                headers={"Origin": "https://untrusted.example"},
            ).status_code,
            403,
        )

    def test_nonlocal_client_is_blocked(self):
        with TestClient(app, client=("203.0.113.10", 1234)) as client:
            self.assertEqual(
                client.post(self.url, json={"question": "요약"}).status_code, 403
            )

    def test_question_history_limits(self):
        for payload in (
            {"question": " "},
            {"question": "x" * 2001},
            {"question": "q", "history": [{"role": "user", "content": "x"}] * 11},
        ):
            self.assertEqual(self.client.post(self.url, json=payload).status_code, 422)

    def test_rate_limit(self):
        answer = social_chat.GroundedAnswer(answer="가상 답변", article_ids=[])
        with patch.object(
            social_chat, "ask_provider", new_callable=AsyncMock, return_value=answer
        ):
            for _ in range(10):
                self.assertEqual(
                    self.client.post(self.url, json={"question": "요약"}).status_code,
                    200,
                )
            self.assertEqual(
                self.client.post(self.url, json={"question": "요약"}).status_code, 429
            )

    def test_provider_error_is_sanitized(self):
        async def fail(*args, **kwargs):
            raise httpx.ConnectError("unit-test-secret-value")

        with patch("httpx.AsyncClient.post", new=fail):
            response = self.client.post(self.url, json={"question": "요약"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret", response.text)

    def test_real_provider_adapter_parses_structured_output(self):
        payload = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "answer": "[가상 자료] 테스트용 응답",
                                    "article_ids": [self.story.articles[0].id],
                                }
                            ),
                        }
                    ],
                }
            ],
        }
        mock = AsyncMock(return_value=httpx.Response(200, json=payload))
        with patch("httpx.AsyncClient.post", new=mock):
            response = self.client.post(self.url, json={"question": "요약"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock.await_args.args[0], "https://api.openai.com/v1/responses")


class EliceChatTests(SocialChatTests):
    def setUp(self):
        super().setUp()
        self.elice_env = patch.dict(
            os.environ,
            {
                "PRISM_CHAT_PROVIDER": "elice",
                "ELICE_API_KEY": "unit-elice-key",
                "ELICE_CHAT_MODEL": "openai/gpt-5-mini",
                "ELICE_API_URL": "https://mlapi.run/00000000-0000-0000-0000-000000000001",
            },
        )
        self.elice_env.start()

    def tearDown(self):
        self.elice_env.stop()
        super().tearDown()

    # The base OpenAI adapter test is provider-specific, so replace its assertion for Elice.
    def test_real_provider_adapter_parses_structured_output(self):
        result = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": "[가상 자료] 엘리스 어댑터 테스트",
                                "article_ids": [self.story.articles[0].id],
                            }
                        )
                    },
                }
            ]
        }
        mock = AsyncMock(return_value=httpx.Response(200, json=result))
        with patch("httpx.AsyncClient.post", new=mock):
            response = self.client.post(self.url, json={"question": "요약"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock.await_args.args[0].startswith("https://mlapi.run/"))
        body = mock.await_args.kwargs["json"]
        self.assertEqual(body["model"], "openai/gpt-5-mini")
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertIn("messages", body)
        self.assertNotIn("store", body)
        self.assertEqual(
            mock.await_args.kwargs["headers"]["Authorization"], "Bearer unit-elice-key"
        )

    def test_endpoint_cannot_send_key_to_another_host(self):
        with (
            patch.dict(
                os.environ,
                {"ELICE_API_URL": "https://untrusted.example/v1/chat/completions"},
            ),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock) as call,
        ):
            self.assertFalse(
                self.client.get("/api/social/chat/status").json()["configured"]
            )
            self.assertEqual(
                self.client.post(self.url, json={"question": "요약"}).status_code, 503
            )
            call.assert_not_awaited()

    def test_auth_error_is_provider_specific_and_sanitized(self):
        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(
                return_value=httpx.Response(401, json={"error": "unit-elice-key"})
            ),
        ):
            response = self.client.post(self.url, json={"question": "요약"})
        self.assertEqual(response.status_code, 502)
        self.assertIn("엘리스", response.json()["error"]["message"])
        self.assertNotIn("unit-elice-key", response.text)

    def test_missing_api_id_is_not_reported_as_bad_key(self):
        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(
                return_value=httpx.Response(
                    404,
                    json={
                        "error": {
                            "code": "api_not_found",
                            "message": "upstream diagnostic",
                        }
                    },
                )
            ),
        ):
            response = self.client.post(self.url, json={"question": "요약"})
        self.assertEqual(response.status_code, 502)
        self.assertIn("API ID", response.json()["error"]["message"])
        self.assertNotIn("upstream diagnostic", response.text)


if __name__ == "__main__":
    unittest.main()
