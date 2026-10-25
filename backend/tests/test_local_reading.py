import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app.api import app
from backend.app import local_article_body as reading
from backend.app.connection_repository import load_snapshot


class LocalReadingTests(unittest.TestCase):
    def test_body_preview_is_disabled_by_default_and_does_not_read_db(self):
        with patch.dict(os.environ,{'PRISM_BODY_PREVIEW_ENABLED':'0'}),patch.object(reading,'story_for') as find:
            self.assertEqual(TestClient(app).get('/api/local/stories/test/body').status_code,403)
            find.assert_not_called()

    def test_bound_body_is_truncated_and_not_mixed_with_other_article(self):
        story=load_snapshot('fixture').stories[0]
        with patch.dict(os.environ,{'PRISM_BODY_PREVIEW_ENABLED':'1','PRISM_DATA_SOURCE':'cluster-db'}), \
                patch.object(reading,'story_for',return_value=story), \
                patch.object(reading,'chat_cluster_bodies',return_value=[{'article_id':story.articles[0].id,'text':'가'*7000,'is_excerpt':False}]):
            r=TestClient(app).get('/api/local/stories/'+story.id+'/body')
        self.assertEqual(r.status_code,200)
        self.assertEqual(len(r.json()['text']),6000)
        self.assertTrue(r.json()['is_excerpt'])

    def test_nonlocal_preview_access_denied(self):
        with patch.dict(os.environ,{'PRISM_BODY_PREVIEW_ENABLED':'1','PRISM_DATA_SOURCE':'cluster-db'}):
            client=TestClient(app,client=('203.0.113.10',1000))
            self.assertEqual(client.get('/api/local/stories/test/body').status_code,403)
