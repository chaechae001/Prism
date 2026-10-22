"""Configuration, publication boundaries, and provider-free chat context tests."""

import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app.api import app
from backend.app import connection_api
from backend.app.chat import router as chat
from backend.app.db import DatabaseConfigurationError, get_engine
from backend.app.connection_repository import load_snapshot
from backend.app.llm.elice_settings import EliceSettings


class IntegrationBoundaryTests(unittest.TestCase):
    def tearDown(self):
        get_engine.cache_clear()
        app.dependency_overrides.clear()

    def test_missing_database_configuration_has_no_fixture_fallback(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("backend.app.db.load_environment"),
        ):
            get_engine.cache_clear()
            with self.assertRaises(DatabaseConfigurationError):
                get_engine()

    def test_remote_database_cannot_disable_tls(self):
        values = {
            "DB_HOST": "example.test",
            "DB_PORT": "5432",
            "DB_NAME": "postgres",
            "DB_USER": "test",
            "DB_PASSWORD": "test-password",
            "DB_SSLMODE": "disable",
        }
        with (
            patch.dict(os.environ, values, clear=True),
            patch("backend.app.db.load_environment"),
        ):
            get_engine.cache_clear()
            with self.assertRaises(DatabaseConfigurationError):
                get_engine()

    def test_database_config_failure_is_sanitized_503(self):
        def failing():
            raise DatabaseConfigurationError("password-do-not-print")

        app.dependency_overrides[connection_api.get_snapshot] = failing
        response = TestClient(app).get("/api/v1/stories")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("password-do-not-print", response.text)
        self.assertEqual(response.json()["error"]["code"], "DATABASE_NOT_CONFIGURED")

    def test_fixture_chat_does_not_connect_to_database(self):
        story = load_snapshot("fixture").stories[0]
        with (
            patch.dict(os.environ, {"PRISM_DATA_SOURCE": "fixture"}),
            patch("backend.app.services.article_context.chat_bodies") as bodies,
        ):
            result = chat.context_for(story)
        bodies.assert_not_called()
        self.assertEqual(result["bodies"], [])

    def test_db_chat_context_failure_is_not_silently_replaced(self):
        story = load_snapshot("fixture").stories[0]
        with (
            patch.dict(os.environ, {"PRISM_DATA_SOURCE": "supabase"}),
            patch(
                "backend.app.services.article_context.chat_bodies",
                side_effect=RuntimeError("offline"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                chat.context_for(story)

    def test_elice_shared_model_setting_is_supported(self):
        values = {
            "ELICE_API_URL": "https://example.test/id/v1/chat/completions",
            "ELICE_API_KEY": "unit-test-key",
            "ELICE_CHAT_MODEL": "openai/gpt-5-mini",
        }
        with (
            patch.dict(os.environ, values, clear=True),
            patch("backend.app.llm.elice_settings.load_dotenv"),
            patch("backend.app.llm.elice_settings.load_environment"),
        ):
            config = EliceSettings.from_env()
        self.assertEqual(config.model, "openai/gpt-5-mini")


if __name__ == "__main__":
    unittest.main()
