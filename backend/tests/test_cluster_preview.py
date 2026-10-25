"""Saved cluster artifacts become review-only Stories without model/DB calls."""

from copy import deepcopy
from hashlib import sha256
import importlib
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def source_article(identity, title='금리 결정 보도', publisher='가상 검증 언론사'):
    body = '본문 앞부분입니다. ' + '원문 문장을 보존합니다. ' * 50
    return dict(article_id=identity, title=title, body=body, category='경제',
        published_at='2026-10-22T09:00:00+09:00', publisher=publisher,
        url='https://example.org/articles/' + identity, source_id='test-source',
        body_kind='provided_body', source_notice='',
        content_hash=sha256(f'{title}\n{body}'.strip().encode()).hexdigest())


def bundle(folder):
    articles = [source_article('a'), source_article('b', title='금리 결정 배경 설명')]
    representative = {**articles[1], 'metadata': {'rights': {'license_status': 'unknown'}}}
    exported = dict(schema_version='local-news-representatives/v1', status='completed',
        article_count=2, group_count=1, automatic_publication=False, accuracy_measured=False,
        groups=[dict(group_id='group-example', category='경제', article_count=2,
            publisher_count=1, article_ids=['a', 'b'], same_event_confirmed=False,
            representative=representative, related_articles=[articles[0]],
            quality_review_required=True,
            quality_review_reasons=['identical_cleaned_body_different_headlines'])])
    save(folder, exported, articles)
    return exported, articles


def save(folder, exported, articles):
    (folder/'representatives.json').write_text(json.dumps(exported, ensure_ascii=False), encoding='utf-8')
    (folder/'articles.json').write_text(json.dumps({'articles': articles}, ensure_ascii=False), encoding='utf-8')


class ClusterPreviewTests(unittest.TestCase):
    def adapter(self):
        self.assertIsNotNone(importlib.util.find_spec('backend.app.cluster_preview'))
        return importlib.import_module('backend.app.cluster_preview')

    def test_source_is_registered_without_replacing_fixture_default(self):
        from backend.app.connection_repository import SOURCES, load_snapshot
        self.assertIn('cluster-local', SOURCES)
        self.assertEqual(load_snapshot('fixture').source, 'fixture')

    def test_representative_is_first_and_original_ids_links_and_category_survive(self):
        api = self.adapter()
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            before, articles = bundle(folder)
            original_bytes = {p.name: p.read_bytes() for p in folder.iterdir()}
            stories, version, notes = api.load_cluster_preview(folder)
            self.assertEqual(len(stories), 1)
            story = stories[0]
            self.assertEqual(story.title, articles[1]['title'])
            self.assertEqual([a.id for a in story.articles], ['b', 'a'])
            self.assertEqual(str(story.articles[0].url), articles[1]['url'])
            self.assertEqual(story.category, 'economy')
            self.assertEqual(story.coverage.article_count, 2)
            self.assertEqual(story.coverage.publisher_count, 1)
            self.assertEqual(story.coverage.label_status, 'unverified')
            self.assertFalse(story.is_demo)
            self.assertTrue(version.startswith('cluster-local-'))
            self.assertTrue(any('2' in note and '1' in note for note in notes))
            self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, original_bytes)

    def test_excerpt_is_bounded_and_never_marked_as_a_generated_summary(self):
        api = self.adapter()
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            _, articles = bundle(folder)
            story = api.load_cluster_preview(folder)[0][0]
            self.assertTrue(story.dek.startswith('대표기사 본문 발췌'))
            self.assertLess(len(story.dek), 300)
            self.assertNotEqual(story.dek, articles[1]['body'])
            self.assertEqual(story.summary.status, 'pending')
            self.assertEqual(story.summary.bullets, [])
            self.assertEqual(story.perspectives, [])
            self.assertIsNone(story.summary.model_version)
            self.assertTrue(any(note.startswith('검토 필요:') for note in story.summary.unknowns))
            self.assertFalse(any('body' in article for article in story.model_dump(mode='json')['articles']))

    def test_bad_counts_membership_or_changed_representative_fail_closed(self):
        api = self.adapter()
        mutations = [
            lambda e,a: e.update(group_count=2),
            lambda e,a: e.update(article_count=1),
            lambda e,a: e['groups'][0].update(article_ids=['a','a']),
            lambda e,a: e['groups'][0].update(article_ids=['a','missing']),
            lambda e,a: e['groups'][0].update(article_count=1),
            lambda e,a: e['groups'][0].update(publisher_count=2),
            lambda e,a: e['groups'][0]['representative'].update(title='Changed title'),
            lambda e,a: e['groups'][0].update(category='unknown'),
            lambda e,a: a[0].update(content_hash='0'*64),
            lambda e,a: a.append(deepcopy(a[0])),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate), TemporaryDirectory() as directory:
                folder = Path(directory)
                exported, articles = bundle(folder)
                mutate(exported, articles)
                save(folder, exported, articles)
                with self.assertRaises(api.ClusterPreviewError):
                    api.load_cluster_preview(folder)

    def test_missing_files_do_not_fall_back_to_fictional_news(self):
        api = self.adapter()
        from backend.app.connection_repository import load_snapshot
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'CLUSTER_RESULTS_DIR': directory}):
            with self.assertRaises(api.ClusterPreviewError):
                load_snapshot('cluster-local')

    def test_stable_ids_and_version_and_no_hidden_metadata_in_public_story(self):
        api = self.adapter()
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            exported, articles = bundle(folder)
            first = api.load_cluster_preview(folder)
            second = api.load_cluster_preview(folder)
            self.assertEqual(first, second)
            serialized = json.dumps(first[0][0].model_dump(mode='json'))
            self.assertNotIn('license_status', serialized)
            self.assertNotIn('content_hash', serialized)
            exported['groups'][0]['quality_review_required'] = False
            exported['groups'][0]['quality_review_reasons'] = []
            save(folder, exported, articles)
            third = api.load_cluster_preview(folder)
            self.assertEqual(first[0][0].id, third[0][0].id)
            self.assertNotEqual(first[1], third[1])

    def test_http_feed_detail_search_and_categories_use_existing_contract(self):
        self.adapter()
        from backend.app import connection_api
        from backend.app.connection_repository import load_snapshot
        with TemporaryDirectory() as directory:
            bundle(Path(directory))
            with patch.dict(os.environ, {'CLUSTER_RESULTS_DIR': directory}):
                connection_api.app.dependency_overrides[connection_api.get_snapshot] = lambda: load_snapshot('cluster-local')
                try:
                    client = TestClient(connection_api.app)
                    feed = client.get('/api/v1/stories?q=금리&category=economy')
                    self.assertEqual(feed.status_code, 200)
                    data = feed.json()
                    self.assertEqual(data['total'], 1)
                    self.assertFalse(data['meta']['is_mock'])
                    self.assertEqual(data['meta']['policy_version'], 'cluster-local-v1')
                    self.assertNotIn('RSS 원문', data['items'][0]['reason']['label'])
                    story_id = data['items'][0]['story']['id']
                    detail = client.get('/api/v1/stories/' + story_id).json()
                    self.assertEqual(detail['story']['title'], '금리 결정 배경 설명')
                    counts = client.get('/api/v1/categories').json()['items']
                    self.assertEqual(next(c['count'] for c in counts if c['id']=='economy'), 1)
                finally:
                    connection_api.app.dependency_overrides.clear()

    def test_missing_snapshot_is_a_sanitized_503(self):
        api = self.adapter()
        from backend.app import connection_api
        def unavailable():
            raise api.ClusterPreviewError('private-path-do-not-print')
        connection_api.app.dependency_overrides[connection_api.get_snapshot] = unavailable
        try:
            response = TestClient(connection_api.app, raise_server_exceptions=False).get('/api/v1/stories')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()['error']['code'], 'CLUSTER_RESULTS_UNAVAILABLE')
            self.assertNotIn('private-path-do-not-print', response.text)
        finally:
            connection_api.app.dependency_overrides.clear()

    def test_cluster_source_keeps_chat_disabled_even_if_provider_settings_exist(self):
        self.adapter()
        from backend.app.chat import router
        with patch.dict(os.environ, {'PRISM_DATA_SOURCE':'cluster-local', 'PRISM_CHAT_ENABLED':'1'}):
            with patch.object(router, 'settings', return_value=('elice','test-key','test-model','https://example.org')):
                self.assertFalse(router.configuration())
                provider = AsyncMock()
                with patch.object(router, 'ask_provider', provider):
                    from backend.app.api import app
                    response = TestClient(app).post('/api/social/stories/not-needed/chat', json={'question':'요약해줘'})
                    self.assertEqual(response.status_code, 503)
                provider.assert_not_called()

    def test_cluster_source_never_reads_dotenv_through_chat_configuration_entrypoint(self):
        from backend.app import config
        from backend.app.chat.config import load_chat_env
        with patch.dict(os.environ, {'PRISM_DATA_SOURCE': 'cluster-local'}):
            with patch.object(config, 'load_dotenv') as loader:
                config.load_environment()
                load_chat_env()
                loader.assert_not_called()

    def test_existing_sources_keep_their_configuration_loading(self):
        from backend.app import config
        with patch.dict(os.environ, {'PRISM_DATA_SOURCE': 'fixture'}):
            with patch.object(config, 'load_dotenv') as loader:
                config.load_environment()
                self.assertEqual(loader.call_count, 2)


if __name__ == '__main__':
    unittest.main()
