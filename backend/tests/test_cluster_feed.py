"""Completed DB candidate batches use existing API without exposing stored bodies."""
from copy import deepcopy
import importlib
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.tests.test_cluster_store import fixture
from backend.app.cluster_store.bundle import prepare_bundle


def candidate():
    with TemporaryDirectory() as d:
        fixture(Path(d))
        value=prepare_bundle(d,namespace='test-db')
    articles=[{k:v for k,v in a.items() if k!='body'} for a in value['payload']['articles']]
    for a in articles:a['image_url']='https://example.org/'+a['article_id']+'.jpg'
    groups=deepcopy(value['payload']['groups'])
    members=[dict(group_id=g['group_id'],article_id=a) for g in groups for a in g.pop('article_ids')]
    return value['batch_id'],articles,groups,members


class ClusterFeedTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('backend.app.cluster_feed'),'Missing DB cluster read adapter')
        return importlib.import_module('backend.app.cluster_feed')

    def test_projection_preserves_original_representative_and_never_exposes_body_or_private_metadata(self):
        m=self.module();batch,articles,groups,members=candidate()
        stories,notes=m.project_batch('test-db',batch,articles,groups,members)
        story=stories[0]
        self.assertTrue(story.id.startswith('db-cluster-'))
        self.assertEqual([a.id for a in story.articles],['b','a'])
        self.assertEqual(story.title,'금리 결정 배경 설명')
        self.assertEqual(story.coverage.article_count,2)
        self.assertEqual(story.coverage.label_status,'unverified')
        self.assertEqual(story.summary.status,'pending')
        self.assertEqual(story.summary.bullets,[])
        encoded=story.model_dump_json()
        for private in ('본문 앞부분입니다','body_sha256','raw_text','rights','record'):
            self.assertNotIn(private,encoded)
        self.assertTrue(all(a.image_url is None for a in story.articles))

    def test_image_display_needs_explicit_permission_and_same_group_ids_are_namespace_bound(self):
        m=self.module();batch,articles,groups,members=candidate()
        articles[1]['rights']['display_image']='allowed'
        story=m.project_batch('test-db',batch,articles,groups,members)[0][0]
        self.assertEqual(str(story.articles[0].image_url),'https://example.org/b.jpg')
        self.assertIsNone(story.articles[1].image_url)
        same=m.project_batch('test-db','prism-batch-'+'1'*64,articles,groups,members)[0][0]
        other=m.project_batch('other','prism-batch-'+'1'*64,articles,groups,members)[0][0]
        self.assertEqual(story.id,same.id)
        self.assertNotEqual(story.id,other.id)

    def test_invalid_partition_or_representative_fails_instead_of_showing_wrong_sources(self):
        m=self.module();batch,articles,groups,members=candidate()
        for mutate in (lambda a,g,mem:mem.pop(),lambda a,g,mem:g[0].update(representative_article_id='missing'),
                       lambda a,g,mem:mem.append(dict(mem[0])),lambda a,g,mem:a.pop()):
            a,g,mem=deepcopy(articles),deepcopy(groups),deepcopy(members)
            mutate(a,g,mem)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):m.project_batch('test-db',batch,a,g,mem)

    def test_registered_source_and_api_filters_details_labels_and_chat_disabled(self):
        m=self.module()
        from backend.app.connection_repository import SOURCES,load_snapshot
        from backend.app import connection_api
        from backend.app.chat.router import configuration
        self.assertIn('cluster-db',SOURCES)
        batch,a,g,mem=candidate();stories,notes=m.project_batch('test-db',batch,a,g,mem)
        with patch.dict(os.environ,{'PRISM_DATA_SOURCE':'cluster-db','PRISM_CLUSTER_NAMESPACE':'test-db','PRISM_CHAT_ENABLED':'1'}),patch.object(m,'load_cluster_feed',return_value=(stories,'cluster-db-test',notes)):
            self.assertFalse(configuration())
            data=load_snapshot('cluster-db')
            self.assertEqual(data.source,'cluster-db')
            connection_api.app.dependency_overrides[connection_api.get_snapshot]=lambda:data
            try:
                with TestClient(connection_api.app) as client:
                    feed=client.get('/api/v1/stories?q=금리&category=economy').json()
                    self.assertEqual(feed['total'],1)
                    self.assertEqual(feed['meta']['policy_version'],'cluster-db-v1')
                    self.assertIn('동일 사건 검토 전',feed['items'][0]['reason']['label'])
                    self.assertEqual(client.get('/api/v1/stories?category=politics').json()['total'],0)
                    detail=client.get('/api/v1/stories/'+stories[0].id).json()
                    self.assertEqual(detail['story']['articles'][0]['id'],'b')
                    self.assertNotIn('본문 앞부분입니다',json.dumps(detail,ensure_ascii=False))
            finally:connection_api.app.dependency_overrides.clear()

    def test_db_source_failure_is_503_and_does_not_fall_back_to_local_files(self):
        m=self.module()
        from backend.app.connection_repository import load_snapshot
        from backend.app import connection_api
        with patch.object(m,'load_cluster_feed',side_effect=m.ClusterFeedError('synthetic')):
            connection_api.app.dependency_overrides[connection_api.get_snapshot]=lambda:load_snapshot('cluster-db')
            try:
                with TestClient(connection_api.app) as client:
                    response=client.get('/api/v1/stories')
                    self.assertEqual(response.status_code,503)
                    self.assertEqual(response.json()['error']['code'],'CLUSTER_DB_UNAVAILABLE')
            finally:connection_api.app.dependency_overrides.clear()


if __name__=='__main__':unittest.main()
