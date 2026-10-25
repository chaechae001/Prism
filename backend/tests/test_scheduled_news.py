"""DB-first scheduling, source policies and retryable analysis boundaries."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.tests.test_cluster_preview import source_article


def options(root, **changes):
    raw = dict(namespace='scheduled-test', interval_seconds=900, window_hours=72,
               max_articles=500, refetch_seconds=21600, limit_per_feed=20,
               min_body_characters=200, profile='v2', model_dir=str(root/'model'),
               work_dir=str(root/'work'), sources=[dict(key='sbs', enabled=True,
               rights=dict(collect='allowed',store='allowed',summarize='unknown',
                           publish_summary='unknown',display_image='unknown'))])
    raw.update(changes)
    return raw


class ScheduledSettingsTests(unittest.TestCase):
    def module(self, suffix):
        self.assertIsNotNone(importlib.util.find_spec('backend.app.scheduled_news'),
                             'Missing independent periodic collection worker')
        return importlib.import_module('backend.app.scheduled_news.'+suffix)

    def test_settings_reject_bad_intervals_duplicate_sources_and_unknown_fields(self):
        m=self.module('settings')
        with TemporaryDirectory() as d:
            raw=options(Path(d))
            settings=m.Settings.model_validate(raw)
            self.assertEqual(settings.interval_seconds,900)
            self.assertEqual([s.key for s in settings.active_sources],['sbs'])
            cases=[dict(interval_seconds=True),dict(interval_seconds=1),dict(max_articles=501),
                   dict(namespace='../other'),dict(profile='unknown'),dict(oops=1),
                   dict(sources=raw['sources']*2),dict(window_hours=0),dict(refetch_seconds=0)]
            for changes in cases:
                with self.subTest(changes=changes),self.assertRaises(ValueError):
                    m.Settings.model_validate({**raw,**changes})

    def test_unapproved_sources_pause_before_importing_db_or_collecting(self):
        m=self.module('settings'); runner=self.module('runner')
        with TemporaryDirectory() as d:
            raw=options(Path(d));raw['sources'][0]['rights']['collect']='unknown'
            settings=m.Settings.model_validate(raw)
            self.assertEqual(settings.active_sources,[])
            def forbidden(*a,**k):raise AssertionError('Paused worker used external boundary')
            with patch('backend.app.cluster_store.repository._engine',side_effect=forbidden):
                result=runner.run_cycle(settings,collector=forbidden)
            self.assertEqual(result['status'],'waiting_for_sources')
            self.assertEqual(result['llm_calls'],0)
            self.assertFalse((Path(d)/'work').exists())

    def test_photo_is_extracted_from_the_same_validated_html_without_second_request(self):
        m=self.module('settings'); c=self.module('collection')
        from rss_fulltext_crawler.rss_crawler.network import Response
        from rss_fulltext_crawler.rss_crawler.parsing import SOURCES
        url='https://news.sbs.co.kr/news/endPage.do?news_id=N1009999999'
        xml=f'<rss><channel><item><title>가상 검증 기사</title><link>{url}</link><pubDate>Fri, 23 Oct 2026 01:00:00 GMT</pubDate></item></channel></rss>'.encode()
        html=(f'<html><head><link rel="canonical" href="{url}"><meta property="og:image" content="https://example.org/test.jpg"></head><body><div class="text_area">'+('가상 뉴스 본문. '*60)+'</div></body></html>').encode()
        class Client:
            requests_made=0
            def get(self,request,max_bytes,identity=None):
                self.requests_made+=1
                return Response(request,200,{'content-type':'text/html' if identity else 'application/rss+xml'},html if identity else xml)
        client=Client()
        with TemporaryDirectory() as d:
            settings=m.Settings.model_validate(options(Path(d)))
            result=c.collect_rows(settings,known_ids=set(),cutoff=datetime(2026,10,23,2,tzinfo=timezone.utc),client=client)
            self.assertEqual(client.requests_made,2)
            self.assertEqual(len(result['articles']),1)
            row=result['articles'][0]
            self.assertEqual(row['status'],'ok')
            self.assertEqual(row['image_url'],'https://example.org/test.jpg')
            self.assertEqual(row['rights']['store'],'allowed')
            self.assertEqual(row['rights']['display_image'],'unknown')
            self.assertGreater(len(row['body']),200)
            client.requests_made=0
            second=c.collect_rows(settings,known_ids={row['article_id']},cutoff=datetime(2026,10,23,2,tzinfo=timezone.utc),client=client)
            self.assertEqual(second['articles'],[])
            self.assertEqual(client.requests_made,1)

    def test_failed_or_truncated_collection_commits_rows_but_keeps_previous_feed(self):
        runner=self.module('runner');settings_module=self.module('settings')
        from contextlib import contextmanager
        class Repo:
            @contextmanager
            def lock(self,*a):yield True
            def known_ids(self,*a,**k):return set()
            def observations(self,*a,**k):return {}
            def ingest(self,*a,**k):return 1
            def read_window(self,*a,**k):raise AssertionError('Incomplete collection advanced analysis')
        with TemporaryDirectory() as d:
            settings=settings_module.Settings.model_validate(options(Path(d)))
            for summary in ({'feed_status_counts':{'robots_denied':1}},{'excluded_articles':20}):
                result=runner.run_cycle(settings,repository=Repo(),analyzer=lambda *a,**k:None,
                    collector=lambda *a,**k:{'articles':[{}],'summary':summary,'complete':False})
                self.assertEqual(result['status'],'collection_incomplete')
                self.assertEqual(result['observed_articles'],1)

    def test_metadata_rights_and_image_changes_change_revision_but_observation_time_does_not(self):
        r=self.module('repository')
        row={**source_article('a'),'rights':dict(collect='allowed',store='allowed',summarize='unknown',publish_summary='unknown',display_image='unknown'),'image_url':None}
        from hashlib import sha256
        from backend.app.cluster_store.bundle import canonical
        revision=lambda a:sha256(canonical(r.stable_row(a)).encode()).hexdigest()
        self.assertEqual(revision(row),revision({**row,'collected_at':'new','rss_fetched_at':'new'}))
        self.assertNotEqual(revision(row),revision({**row,'image_url':'https://example.org/new.jpg'}))
        changed=deepcopy(row);changed['rights']['display_image']='allowed'
        self.assertNotEqual(revision(row),revision(changed))

    def test_unseen_backlog_has_priority_even_when_recent_exclusions_expire_between_cycles(self):
        settings_module=self.module('settings');c=self.module('collection')
        from rss_fulltext_crawler.rss_crawler.network import Response
        cutoff=datetime(2026,10,23,2,tzinfo=timezone.utc)
        urls=['https://news.sbs.co.kr/news/endPage.do?news_id=N100999999'+str(i) for i in range(3)]
        xml=('<rss><channel>'+''.join(f'<item><title>가상 기사 {i}</title><link>{url}</link><pubDate>Fri, 23 Oct 2026 01:00:00 GMT</pubDate></item>' for i,url in enumerate(urls))+'</channel></rss>').encode()
        class Client:
            requests_made=0
            def get(self,url,max_bytes,identity=None):
                self.requests_made+=1
                html=(f'<link rel="canonical" href="{url}"><div class="text_area">'+('가상 본문. '*70)+'</div>').encode()
                return Response(url,200,{'content-type':'text/html' if identity else 'application/rss+xml'},html if identity else xml)
        with TemporaryDirectory() as d:
            settings=settings_module.Settings.model_validate(options(Path(d),limit_per_feed=2,refetch_seconds=300))
            first=c.collect_rows(settings,known_ids=set(),cutoff=cutoff,client=Client())
            self.assertFalse(first['complete']);self.assertEqual(len(first['articles']),2)
            observed={r['article_id']:cutoff for r in first['articles']}
            second=c.collect_rows(settings,known_ids=set(),observations=observed,cutoff=cutoff.replace(minute=15),client=Client())
            self.assertTrue(second['complete'])
            self.assertEqual(len({r['article_id'] for r in first['articles']+second['articles']}),3)

    def test_model_bytes_invalidate_the_worker_unchanged_shortcut(self):
        runner=self.module('runner');settings_module=self.module('settings')
        with TemporaryDirectory() as d:
            root=Path(d);model=root/'model';(model/'onnx').mkdir(parents=True)
            (model/'tokenizer.json').write_text('tokenizer-v1')
            (model/'onnx/model_quantized.onnx').write_bytes(b'model-v1')
            settings=settings_module.Settings.model_validate(options(root))
            first=runner._input_hash([],settings)
            (model/'onnx/model_quantized.onnx').write_bytes(b'model-v2')
            self.assertNotEqual(first,runner._input_hash([],settings))
            second=runner._input_hash([],settings)
            (model/'tokenizer.json').write_text('tokenizer-v2')
            self.assertNotEqual(second,runner._input_hash([],settings))

    def test_inbox_validation_rejects_body_hash_rights_and_identity_conflicts(self):
        r=self.module('repository')
        row={**source_article('a'),'rights':dict(collect='allowed',store='allowed',summarize='unknown',publish_summary='unknown',display_image='unknown'),'image_url':None}
        self.assertEqual(r.validate_rows([row])[0]['body'],row['body'])
        for changes in ({'content_hash':'0'*64},{'body':'wrong'},{'rights':{}},{'published_at':None}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):r.validate_rows([{**row,**changes}])
        with self.assertRaises(ValueError):r.validate_rows([row,{**row,'article_id':'different'}])
        with self.assertRaises(ValueError):r.validate_rows([row,{**row,'url':'https://example.org/other'}])


class ScheduledRunnerTests(unittest.TestCase):
    def module(self,suffix):return importlib.import_module('backend.app.scheduled_news.'+suffix)
    def test_db_readback_is_analysis_input_and_failed_analysis_remains_retryable(self):
        m=self.module('settings');run=self.module('runner')
        row={**source_article('a'),'source_id':'sbs-economy','rights':dict(collect='allowed',store='allowed',summarize='unknown',publish_summary='unknown',display_image='unknown'),'image_url':None}
        from contextlib import contextmanager
        events=[]
        class Repo:
            @contextmanager
            def lock(self,namespace):yield True
            def known_ids(self,*a,**k):return set()
            def observations(self,*a,**k):return {}
            def ingest(self,namespace,rows,**kwargs):events.append('committed-inbox');self.rows=deepcopy(rows);return len(rows)
            def read_window(self,*a,**k):events.append('read-db');return deepcopy(self.rows)
            def latest_input_hash(self,*a,**k):return None
            def store(self,*a,**k):raise AssertionError('Failed analysis wrote result')
        repo=Repo()
        def collect(*a,**k):events.append('collect');return {'articles':[row],'summary':{}}
        def analyze(raw,output,**k):
            events.append('analyze')
            self.assertEqual(raw,repo.rows)
            raise RuntimeError('synthetic failure with SECRET=must-not-log')
        with TemporaryDirectory() as d:
            settings=m.Settings.model_validate(options(Path(d)))
            with self.assertRaises(RuntimeError):run.run_cycle(settings,repository=repo,collector=collect,analyzer=analyze)
            self.assertEqual(events,['collect','committed-inbox','read-db','analyze'])
            self.assertEqual(repo.rows[0]['article_id'],'a')

    def test_periodic_loop_records_redacted_failure_and_stops_without_busy_retry(self):
        m=self.module('settings');runner=self.module('runner')
        class Stop:
            waits=[]
            def is_set(self):return bool(self.waits)
            def wait(self,seconds):self.waits.append(seconds);return True
        stop=Stop()
        def fail(*a,**k):raise RuntimeError('PASSWORD=do-not-expose')
        with TemporaryDirectory() as d:
            settings=m.Settings.model_validate(options(Path(d)))
            runner.run_forever(settings,stop=stop,cycle=fail)
            status=json.loads((settings.work_dir/'status.json').read_text())
            self.assertEqual(status['status'],'failed')
            self.assertEqual(status['error_type'],'RuntimeError')
            self.assertNotIn('PASSWORD',json.dumps(status))
            self.assertEqual(stop.waits,[900])

    def test_image_manifest_is_deterministic_for_a_previously_seen_input(self):
        runner=self.module('runner')
        from backend.tests.test_cluster_store import fixture
        with TemporaryDirectory() as d:
            root=Path(d);folder=root/'analysis';folder.mkdir()
            _,rows=fixture(folder)
            for row in rows:row.update(rights={'display_image':'unknown'},image_url=None)
            runner._images(rows,folder,root/'first.json')
            runner._images(rows,folder,root/'second.json')
            self.assertEqual((root/'first.json').read_bytes(),(root/'second.json').read_bytes())


if __name__=='__main__':unittest.main()


class PoliticsFeedTests(unittest.TestCase):
    def test_political_feed_preserves_publisher_identity_and_original_category(self):
        from rss_fulltext_crawler.rss_crawler.parsing import feed_source,parse_feed,article_identity
        from backend.app.scheduled_news.settings import SourcePolicy
        source=feed_source('sbs','politics')
        self.assertIn('sectionId=01',source.feed_url)
        url='https://news.sbs.co.kr/news/endPage.do?news_id=N1009999999'
        rows=parse_feed(f'<rss><channel><item><title>가상 국회 기사</title><link>{url}</link></item></channel></rss>'.encode(),source)
        self.assertEqual(rows[0]['source_id'],'sbs-politics');self.assertEqual(rows[0]['category'],'politics')
        self.assertEqual(article_identity(url)[0],'sbs')
        self.assertEqual(SourcePolicy(key='sbs').categories,['economy'])
        with self.assertRaises(ValueError):SourcePolicy(key='sbs',categories=['politics','politics'])
