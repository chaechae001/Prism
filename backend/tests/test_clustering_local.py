"""Local integration contract; model/DB/provider calls are injected or blocked."""

from copy import deepcopy
from hashlib import sha256
import importlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from backend.app.models import AnalystBatch, ArticleInput


def team_article(identity, **changes):
    body = '가상 노사 임금 협상에서 합의안을 발표했습니다.'
    row = dict(id=identity, canonical_url='https://example.org/news/' + identity,
        publisher_id='publisher-' + identity, publisher_group_id='owner-' + identity,
        title='가상 노사 임금 협상 합의', text=body,
        published_at='2026-10-23T09:00:00+09:00',
        collected_at='2026-10-23T09:10:00+09:00', category='economy',
        content_hash=sha256(body.encode()).hexdigest(), license_status='allowed',
        allowed_uses=['collect', 'store', 'summarize', 'publish_summary'])
    row.update(changes)
    return row


def team_batch(*articles):
    return dict(schema_version='1.0', batch_id='synthetic-local-001', articles=list(articles))


def collector_article(identity='a', **changes):
    row = dict(article_id=identity, title='가상 노사 임금 협상 합의',
        body='가상 노사 임금 협상에서 합의안을 발표했습니다.',
        url='https://example.org/news/' + identity, publisher='가상 언론사', source_id='sbs',
        category='economy', published_at='2026-10-23T09:00:00+09:00',
        body_kind='publisher_html', status='ok',
        rights={'license_status': 'unknown', 'allowed_uses': []})
    row.update(changes)
    return row


class FixedEncoder:
    model_id = 'offline-integration-test'
    last_diagnostics = {'backend': 'test'}

    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return np.asarray([[1., 0.]] * len(texts), dtype=np.float32)


class ClusteringAvailabilityTests(unittest.TestCase):
    def test_local_clustering_worker_is_available(self):
        self.assertIsNotNone(
            importlib.util.find_spec('backend.app.clustering'),
            'The existing Clusterer protocol needs a local implementation',
        )


class LocalClusteringTests(unittest.TestCase):
    def adapter(self):
        self.assertIsNotNone(importlib.util.find_spec('backend.app.clustering'))
        module = importlib.import_module('backend.app.clustering')
        self.assertTrue(callable(getattr(module, 'run_batch', None)), 'Missing local run_batch')
        return module

    def test_vendored_imports_resolve_inside_this_team_checkout(self):
        self.adapter()
        import news_clustering.bot
        import rss_fulltext_crawler.rss_crawler.runner
        analysis = Path(__file__).resolve().parents[2] / 'analysis'
        for module in (news_clustering.bot, rss_fulltext_crawler.rss_crawler.runner):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(analysis))

    def test_team_whitespace_body_is_rejected_before_artifacts_or_encoding(self):
        api = self.adapter()
        source = team_article('a', text=' \r\n\t ')
        source['content_hash'] = sha256(source['text'].encode()).hexdigest()
        article = ArticleInput.model_validate(source)
        encoder = FixedEncoder()
        with TemporaryDirectory() as directory:
            target = Path(directory)/'run'
            with self.assertRaises(ValueError):
                api.run_batch(team_batch(source), target, encoder=encoder)
            self.assertFalse(target.exists())
        with self.assertRaises(ValueError):
            api.NewsClusterer(encoder=encoder).cluster([article])
        self.assertEqual(encoder.calls, [])

    def test_team_contract_keeps_identical_bodies_as_separate_article_ids(self):
        api = self.adapter()
        raw = team_batch(team_article('a'), team_article('b'))
        original = deepcopy(raw)
        with TemporaryDirectory() as directory:
            result = api.run_batch(raw, Path(directory)/'run', encoder=FixedEncoder())
            self.assertEqual(result['article_count'], 2)
            self.assertEqual(result['group_count'], 1)
            self.assertEqual(result['groups'][0]['article_ids'], ['a', 'b'])
            self.assertIn(result['groups'][0]['representative']['article_id'], ['a', 'b'])
            saved = json.loads((Path(directory)/'run/representatives.json').read_text(encoding='utf-8'))
            self.assertEqual(saved, result)
            self.assertFalse(result['accuracy_measured'])
            self.assertFalse(result['automatic_publication'])
        self.assertEqual(raw, original)

    def test_team_body_hash_is_preserved_separately_from_core_title_body_hash(self):
        api = self.adapter()
        source = team_article('a', text='  원문\r\n본문  ')
        source['content_hash'] = sha256(source['text'].encode()).hexdigest()
        with TemporaryDirectory() as directory:
            result = api.run_batch(team_batch(source), Path(directory)/'run', encoder=FixedEncoder())
            rep = result['groups'][0]['representative']
            self.assertEqual(rep['body'], source['text'])
            self.assertEqual(rep['metadata']['analyst_metadata']['content_hash'], source['content_hash'])
            self.assertNotEqual(rep['content_hash'], source['content_hash'])

    def test_invalid_team_input_fails_before_encoder_or_output(self):
        api = self.adapter()
        cases = [team_batch(), team_batch(team_article('a', content_hash='0'*64)),
            team_batch(team_article('a', license_status='unknown')),
            team_batch(team_article('a', allowed_uses=['collect'])),
            team_batch(team_article('a', id=' ')), team_batch(team_article('a', title=' ')),
            team_batch(team_article('a', publisher_group_id=' ')),
            team_batch(team_article('a', canonical_url='https://user:password@example.org/a')),
            team_batch(team_article('a'), team_article('a')),
            team_batch(team_article('a'), team_article('b', canonical_url='https://example.org/news/a'))]
        for raw in cases:
            with self.subTest(raw=raw), TemporaryDirectory() as directory:
                encoder = FixedEncoder()
                target = Path(directory)/'run'
                with self.assertRaises(ValueError):
                    api.run_batch(raw, target, encoder=encoder)
                self.assertEqual(encoder.calls, [])
                self.assertFalse(target.exists())

    def test_explicit_collector_input_preserves_unknown_rights_without_claiming_permission(self):
        api = self.adapter()
        raw = {'articles': [collector_article()]}
        original = deepcopy(raw)
        with TemporaryDirectory() as directory:
            target = Path(directory)/'run'
            result = api.run_batch(raw, target, input_format='collector', encoder=FixedEncoder())
            self.assertEqual(result['groups'][0]['representative']['metadata']['rights'],
                             raw['articles'][0]['rights'])
            handoff = json.loads((target/'handoff.json').read_text(encoding='utf-8'))
            self.assertFalse(handoff['team_rights_validated'])
            self.assertFalse(handoff['ready_for_publication'])
        self.assertEqual(raw, original)

    def test_collector_skips_rss_descriptions_and_missing_bodies(self):
        api = self.adapter()
        with TemporaryDirectory() as directory:
            encoder = FixedEncoder()
            result = api.run_batch([collector_article(body_kind='rss_description')],
                Path(directory)/'run', input_format='collector', encoder=encoder)
            self.assertEqual(result['status'], 'no_eligible_articles')
            self.assertEqual(result['skipped_count'], 1)
            self.assertEqual(encoder.calls, [])

    def test_collector_format_must_be_explicit_for_collector_records(self):
        api = self.adapter()
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                api.run_batch([collector_article()], Path(directory)/'run', encoder=FixedEncoder())

    def test_existing_output_and_internal_cache_are_refused_without_mutation(self):
        api = self.adapter()
        with TemporaryDirectory() as directory:
            target = Path(directory)/'run'
            target.mkdir()
            sentinel = target/'keep.txt'
            sentinel.write_text('existing result', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                api.run_batch(team_batch(team_article('a')), target, encoder=FixedEncoder())
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'existing result')
            fresh = Path(directory)/'fresh'
            with self.assertRaises(ValueError):
                api.run_batch(team_batch(team_article('a')), fresh,
                    cache_path=fresh/'cache.sqlite3', encoder=FixedEncoder())
            self.assertFalse(fresh.exists())

    def test_encoder_failure_does_not_publish_completed_output(self):
        api = self.adapter()
        with TemporaryDirectory() as directory:
            target = Path(directory)/'run'
            encoder = FixedEncoder()
            with patch.object(encoder, 'encode', side_effect=RuntimeError('failed inference')):
                with self.assertRaises(RuntimeError):
                    api.run_batch(team_batch(team_article('a')), target, encoder=encoder)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_multiview_anchor_remains_opt_in_and_exports_review_diagnostics(self):
        api = self.adapter()
        raw = team_batch(team_article('a'), team_article('b', title='가상 임금 합의 배경 설명'))
        with TemporaryDirectory() as directory:
            result = api.run_batch(raw, Path(directory)/'run', profile='multiview-anchor',
                                   encoder=FixedEncoder())
            self.assertEqual(result['profile'], 'multiview-anchor')
            self.assertEqual(result['quality_audit']['shared_summary_cluster_count'], 1)
            self.assertEqual(result['quality_audit']['article_ids_requiring_review'], ['a', 'b'])

    def test_protocol_adapter_returns_groups_of_original_ids(self):
        api = self.adapter()
        worker = api.NewsClusterer(encoder=FixedEncoder())
        result = worker.cluster([ArticleInput.model_validate(team_article('a')),
                                 ArticleInput.model_validate(team_article('b'))])
        self.assertEqual(result, [['a', 'b']])
        self.assertEqual(worker.cluster([]), [])

    def test_invalid_profile_or_input_format_is_rejected(self):
        api = self.adapter()
        with TemporaryDirectory() as directory:
            for options in ({'profile': 'unknown'}, {'input_format': 'rss'}, {'profile': None}):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    api.run_batch(team_batch(team_article('a')), Path(directory)/'run',
                                  encoder=FixedEncoder(), **options)

    def test_mutated_model_instance_is_revalidated(self):
        api = self.adapter()
        raw = AnalystBatch.model_validate(team_batch(team_article('a')))
        raw.articles[0].license_status = 'denied'
        with TemporaryDirectory() as directory, self.assertRaises(ValueError):
            api.run_batch(raw, Path(directory)/'run', encoder=FixedEncoder())

    def test_cli_exposes_flags_and_sanitizes_failure(self):
        self.adapter()
        cli = importlib.import_module('backend.app.clustering.__main__')
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            with self.assertRaises(SystemExit) as stop:
                cli.main(['--help'])
        self.assertEqual(stop.exception.code, 0)
        self.assertIn('--input-format', output.getvalue())
        with TemporaryDirectory() as directory:
            source = Path(directory)/'input.json'
            source.write_text(json.dumps(team_batch(team_article('a'))), encoding='utf-8')
            with patch.object(cli, 'run_batch', side_effect=RuntimeError('private-token-must-not-print')):
                with patch('sys.stderr', new_callable=io.StringIO) as error:
                    status = cli.main(['--input', str(source), '--output-dir', str(Path(directory)/'run')])
            self.assertEqual(status, 2)
            self.assertNotIn('private-token-must-not-print', error.getvalue())


if __name__ == '__main__':
    unittest.main()
