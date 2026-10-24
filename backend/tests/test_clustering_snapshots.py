"""Exercise supplied, hash-bound snapshots through the existing public API."""
from hashlib import sha256
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import connection_api
from backend.app.cluster_preview import load_cluster_preview
from backend.app.connection_repository import Snapshot

BASE = Path(__file__).resolve().parents[2] / 'testdata/clustering'


class SuppliedSnapshotTests(unittest.TestCase):
    def test_cluster_local_uses_bundled_snapshot_without_private_configuration(self):
        from backend.app.connection_repository import load_snapshot
        with patch.dict(os.environ, {}, clear=True):
            snapshot = load_snapshot('cluster-local')
        self.assertEqual(len(snapshot.stories), 20)
        self.assertTrue(all(s.articles[0].image_url for s in snapshot.stories))
        self.assertTrue(snapshot.preview)

    def test_supplied_files_match_manifest_and_expected_counts(self):
        manifest = json.loads((BASE / 'manifest.json').read_text(encoding='utf-8'))
        for name, expected in manifest['datasets'].items():
            with self.subTest(dataset=name):
                folder = BASE / name
                for filename, fingerprint in expected['files'].items():
                    blob = (folder / filename).read_bytes()
                    self.assertEqual(len(blob), fingerprint['bytes'])
                    self.assertEqual(sha256(blob).hexdigest(), fingerprint['sha256'])
                stories, _, _ = load_cluster_preview(folder, folder / 'images.json')
                self.assertEqual(len(stories), expected['groups'])
                self.assertEqual(sum(len(s.articles) for s in stories), expected['articles'])
                self.assertTrue(all(s.articles[0].image_url for s in stories))

    def test_both_snapshots_paginate_filter_and_resolve_every_detail(self):
        for name, total in [('anchor92', 74), ('scheduled-sbs', 20)]:
            with self.subTest(dataset=name):
                folder = BASE / name
                stories, version, notes = load_cluster_preview(folder, folder / 'images.json')
                snapshot = Snapshot(stories, version, False, 'cluster-local', notes, preview=True)
                overrides = connection_api.app.dependency_overrides
                overrides[connection_api.get_snapshot] = lambda: snapshot
                try:
                    with TestClient(connection_api.app) as client:
                        seen = set()
                        cursor = None
                        while True:
                            query = {'limit': 20}
                            if cursor:
                                query['cursor'] = cursor
                            response = client.get('/api/v1/stories', params=query)
                            self.assertEqual(response.status_code, 200)
                            page = response.json()
                            self.assertEqual(page['total'], total)
                            self.assertEqual(page['meta']['policy_version'], 'cluster-local-v1')
                            for item in page['items']:
                                story = item['story']
                                self.assertNotIn(story['id'], seen)
                                seen.add(story['id'])
                                detail = client.get('/api/v1/stories/' + story['id'])
                                self.assertEqual(detail.status_code, 200)
                                self.assertEqual(detail.json()['story'], story)
                                self.assertEqual(story['summary']['status'], 'pending')
                                self.assertEqual(story['summary']['bullets'], [])
                                self.assertTrue(all('body' not in a for a in story['articles']))
                            cursor = page['next_cursor']
                            if cursor is None:
                                break
                        self.assertEqual(len(seen), total)
                        counts = client.get('/api/v1/categories').json()['items']
                        self.assertEqual(sum(c['count'] for c in counts), total)
                        for category in counts:
                            response = client.get('/api/v1/stories', params={'category': category['id']})
                            self.assertEqual(response.json()['total'], category['count'])
                        phrase = stories[0].title[:8]
                        result = client.get('/api/v1/stories', params={'q': phrase}).json()
                        self.assertGreaterEqual(result['total'], 1)
                        missing = client.get('/api/v1/stories/not-an-existing-cluster')
                        self.assertEqual(missing.status_code, 404)
                finally:
                    overrides.pop(connection_api.get_snapshot, None)
