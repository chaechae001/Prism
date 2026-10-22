import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app, repo
from app.models import Story, AnalystBatch, SummaryOutput
from app.pipeline import allowed_articles, validate_summary

class ApiTests(unittest.TestCase):
    def setUp(self): self.client=TestClient(app)

    def test_feed_pagination_and_cursor_binding(self):
        first=self.client.get('/api/v1/stories?limit=3').json()
        self.assertEqual(first['total'],12)
        second=self.client.get('/api/v1/stories',params={'limit':3,'cursor':first['next_cursor']}).json()
        self.assertFalse({i['story']['id'] for i in first['items']} & {i['story']['id'] for i in second['items']})
        changed=self.client.get('/api/v1/stories',params={'category':'politics','cursor':first['next_cursor']})
        self.assertEqual(changed.status_code,422)
        self.assertEqual(self.client.get('/api/v1/stories?cursor=garbage').status_code,422)

    def test_filters_and_order(self):
        rows=self.client.get('/api/v1/stories?category=technology&q=AI').json()['items']
        self.assertEqual([i['story']['id'] for i in rows],['story-001'])
        self.assertEqual(self.client.get('/api/v1/stories?q=nothing-matches').json()['total'],0)
        latest=self.client.get('/api/v1/stories?mode=latest&limit=20').json()['items']
        dates=[i['story']['updated_at'] for i in latest]
        self.assertEqual(dates,sorted(dates,reverse=True))
        balanced=self.client.get('/api/v1/stories?diversity=100&limit=4').json()['items']
        self.assertEqual(len({i['story']['category'] for i in balanced}),4)

    def test_errors_are_consistent(self):
        for path in ['/api/v1/stories?category=bad','/api/v1/stories?diversity=101','/api/v1/stories?limit=0','/api/v1/stories?limit=1.5','/api/v1/stories?mode=bad','/api/v1/stories/missing']:
            response=self.client.get(path)
            self.assertIn(response.status_code,[404,422])
            self.assertEqual(response.json()['error']['request_id'],response.headers['X-Request-ID'])
        self.assertEqual(self.client.get('/api/v1/stories',headers={'X-Mock-Scenario':'error'}).status_code,503)
        self.assertEqual(self.client.get('/api/v1/stories',headers={'X-Mock-Scenario':'empty'}).json()['items'],[])

    def test_fixtures_and_citations(self):
        self.assertEqual(len({s.id for s in repo.all()}),12)
        for s in repo.all():
            Story.model_validate(s)
            ids={a.id for a in s.articles}
            self.assertEqual(s.coverage.article_count,len(s.articles))
            self.assertEqual(s.coverage.publisher_count,len({a.publisher_id for a in s.articles}))
            for claim in [*s.summary.bullets,*s.perspectives]:
                self.assertTrue(claim.article_ids and set(claim.article_ids)<=ids)
            if s.summary.status!='ready': self.assertEqual(s.summary.bullets,[])

    def test_detail_and_feedback_validation(self):
        value=self.client.get('/api/v1/stories/story-001').json()
        self.assertEqual(value['story']['id'],'story-001')
        response=self.client.post('/api/v1/feedback',json={'story_id':'story-001','kind':'more_perspectives'})
        self.assertEqual(response.status_code,201)
        self.assertFalse(response.json()['persisted'])
        self.assertEqual(self.client.post('/api/v1/feedback',json={'story_id':'missing','kind':'useful'}).status_code,404)
        self.assertEqual(self.client.post('/api/v1/feedback',json={'story_id':'story-001','kind':'bad'}).status_code,422)

    def test_admin_jobs_closed_by_default(self):
        self.assertEqual(self.client.post('/api/v1/internal/jobs',json={'stage':'cluster'}).status_code,401)
        with patch.dict(os.environ,{'MOCK_ADMIN_TOKEN':'unit-test-token'}):
            headers={'X-Admin-Token':'unit-test-token'}
            self.assertEqual(self.client.post('/api/v1/internal/jobs',headers=headers,json={'stage':'cluster','dry_run':False}).status_code,422)
            r=self.client.post('/api/v1/internal/jobs',headers=headers,json={'stage':'cluster','dry_run':True})
            self.assertEqual(r.status_code,202)
            path='/api/v1/internal/jobs/'+r.json()['id']
            self.assertEqual(self.client.get(path,headers=headers).json()['status'],'running')
            self.assertEqual(self.client.get(path,headers=headers).json()['status'],'succeeded')

    def test_handoff_rights_and_summary_boundary(self):
        root=Path(__file__).resolve().parents[2]
        batch=AnalystBatch.model_validate_json((root/'contracts/analyst-batch.example.json').read_text(encoding='utf-8'))
        a=allowed_articles(batch)[0]
        b=a.model_copy(update={'id':'b','publisher_group_id':'g-02','content_hash':'different','canonical_url':'https://example.com/b'})
        summary=SummaryOutput(title='t',bullets=[{'text':'claim','article_ids':[a.id]}],perspectives=[],unknowns=[])
        with self.assertRaises(ValueError): validate_summary(summary,[a])
        self.assertIs(validate_summary(summary,[a,b]),summary)
        bad=summary.model_copy(update={'bullets':[summary.bullets[0].model_copy(update={'article_ids':['not-in-event']})]})
        with self.assertRaises(ValueError): validate_summary(bad,[a,b])
        denied=batch.model_copy(update={'articles':[a.model_copy(update={'license_status':'unknown'})]})
        self.assertEqual(allowed_articles(denied),[])

if __name__=='__main__': unittest.main()
