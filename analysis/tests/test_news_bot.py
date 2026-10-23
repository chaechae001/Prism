from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from threadpoolctl import threadpool_limits

from news_clustering.bot import main, prepare_articles, run_bot
from news_clustering.bot_report import render_report


def item(identity, body='노사가 임금 협상안에 합의했습니다.', **extra):
    return {'article_id': identity, 'title': '노사 임금 협상 합의', 'body': body,
            'category': 'economy', 'published_at': '2026-10-22T09:00:00Z',
            'url': 'https://example.org/news/' + identity, 'publisher': '언론사',
            'source_id': 'sbs', 'status': 'ok', 'body_kind': 'publisher_html',
            'publisher_article_id': 'publisher-' + identity, 'rss_guid': 'guid-' + identity,
            'rss_description': 'RSS 설명이며 본문과 다릅니다.',
            'rights': {'license_status': 'unknown', 'allowed_uses': []}, **extra}


class FixedEncoder:
    model_id = 'offline-news-bot-test'
    last_diagnostics = {'backend': 'test'}

    def __init__(self, vectors=None):
        self.vectors = vectors
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return np.asarray(self.vectors if self.vectors is not None else [[1., 0.]] * len(texts), dtype=np.float32)


class NewsBotTests(unittest.TestCase):
    def test_crawler_metadata_and_body_are_preserved_without_rss_fallback(self):
        records = [item('a'), item('bad', body=None, status='body_not_found'),
                   item('empty', body=' '), item('snippet', body_kind='rss_description')]
        source = {'schema_version': 'rss-fulltext/1.0', 'results': records}
        before = deepcopy(source)
        articles, metadata, skipped = prepare_articles(source)
        self.assertEqual([a.article_id for a in articles], ['a'])
        self.assertEqual(articles[0].body, records[0]['body'])
        self.assertEqual(metadata['a']['rss_guid'], 'guid-a')
        self.assertEqual(metadata['a']['rights']['license_status'], 'unknown')
        self.assertEqual(len(skipped), 3)
        self.assertEqual(source, before)

    def test_duplicate_ids_and_changed_content_hash_fail_before_encoding(self):
        for records in ([item('a'), item('a')], [item('a', content_hash='0' * 64)]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                prepare_articles(records)

    def test_collector_failed_items_without_an_article_id_do_not_abort_valid_bodies(self):
        records = [item('a'), {'article_id': None, 'title': '링크 누락 항목', 'status': 'missing_article_url',
                              'body': None, 'rss_guid': 'unusable-guid'},
                   {'article_id': None, 'title': '지원하지 않는 링크', 'status': 'unsupported_article_url',
                    'body': None, 'url': 'https://example.org/other'}]
        articles, metadata, skipped = prepare_articles({'results': records})
        self.assertEqual([article.article_id for article in articles], ['a'])
        self.assertEqual(len(skipped), 2)
        self.assertTrue(all(row['article_id'] is None for row in skipped))
        self.assertEqual(skipped[0]['reason'], 'collection_status:missing_article_url')

    def test_one_representative_per_group_is_the_existing_core_mean_similarity_choice(self):
        # b is closest to both endpoints; this proves selection is not first/latest/longest.
        records = [item('a'), item('b', body='노사 임금 협상안에 최종 합의했습니다.'), item('c')]
        encoder = FixedEncoder([[1., -.1], [1., 0.], [1., .1]])
        with TemporaryDirectory() as directory, threadpool_limits(limits=2):
            folder = Path(directory) / 'run'
            result = run_bot(records, folder, encoder=encoder)
            groups = result['groups']
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]['representative']['article_id'], 'b')
            self.assertEqual(groups[0]['article_count'], 3)
            self.assertEqual(len(groups[0]['related_articles']), 2)
            self.assertEqual(groups[0]['representative']['metadata']['rss_guid'], 'guid-b')
            self.assertEqual(groups[0]['representative']['body'], records[1]['body'])
            native = json.loads((folder / 'clustering.json').read_text(encoding='utf-8'))
            self.assertEqual(native['algorithm_version'], 'kmeans-title-evidence/v2')
            self.assertEqual(native['groups'][0]['representative_article_id'], 'b')
            self.assertEqual(native['config']['min_similarity'], .94)
            self.assertFalse(result['automatic_publication'])
            self.assertFalse(result['accuracy_measured'])
            self.assertEqual(result['llm_calls'], 0)
            self.assertEqual(result['shared_database_writes'], 0)
            self.assertTrue((folder / 'vectors.npz').is_file())
            self.assertEqual(len(encoder.calls), 1)

    def test_different_articles_can_remain_singletons_with_themselves_as_representatives(self):
        records = [item('a'), item('b', title='은행 예금 상품 출시', body='새로운 예금 상품을 출시했습니다.')]
        with TemporaryDirectory() as directory, threadpool_limits(limits=2):
            result = run_bot(records, Path(directory) / 'run', encoder=FixedEncoder([[1., 0.], [0., 1.]]))
            self.assertEqual(len(result['groups']), 2)
            self.assertEqual({g['representative']['article_id'] for g in result['groups']}, {'a', 'b'})
            self.assertTrue(all(g['representative_mean_cosine'] is None for g in result['groups']))

    def test_no_usable_bodies_records_empty_run_without_loading_a_model(self):
        with TemporaryDirectory() as directory, patch('news_clustering.bot.CachedNewsE5Encoder') as encoder:
            folder = Path(directory) / 'run'
            result = run_bot([item('bad', body=None, status='body_not_found')], folder)
            encoder.assert_not_called()
            self.assertEqual(result['groups'], [])
            self.assertEqual(result['status'], 'no_eligible_articles')
            self.assertEqual(len(json.loads((folder / 'skipped.json').read_text(encoding='utf-8'))), 1)
            self.assertFalse((folder / 'vectors.npz').exists())

    def test_existing_output_is_rejected_before_model_or_file_writes(self):
        with TemporaryDirectory() as directory, patch('news_clustering.bot.CachedNewsE5Encoder') as encoder:
            folder = Path(directory)
            marker = folder / 'marker'
            marker.write_text('keep', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                run_bot([item('a')], folder)
            encoder.assert_not_called()
            self.assertEqual(marker.read_text(encoding='utf-8'), 'keep')

    def test_saved_input_cli_never_collects_and_keeps_exact_source_file_hash(self):
        with TemporaryDirectory() as directory, patch('news_clustering.bot.collect') as collect:
            folder = Path(directory)
            source = folder / 'source.json'
            source.write_text(json.dumps({'articles': [item('a')]}, ensure_ascii=False), encoding='utf-8')
            before = sha256(source.read_bytes()).hexdigest()
            with patch('news_clustering.bot.CachedNewsE5Encoder', return_value=FixedEncoder()), redirect_stdout(StringIO()):
                code = main(['--input', str(source), '--output', str(folder / 'output')])
            collect.assert_not_called()
            self.assertEqual(code, 0)
            manifest = json.loads((folder / 'output/run.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['input_sha256'], before)
            self.assertEqual(sha256(source.read_bytes()).hexdigest(), before)

    def test_live_rss_cli_reuses_crawler_and_preserves_failed_records(self):
        collection = {'schema_version': 'rss-fulltext/1.0', 'created_at': '2026-10-22T10:00:00Z',
                      'results': [item('a'), item('bad', body=None, status='body_not_found')],
                      'summary': {'selected_articles': 2, 'extracted_count': 1, 'http_requests': 4},
                      'collection': {'database_writes': 0}, 'source_reports': []}
        with TemporaryDirectory() as directory, patch('news_clustering.bot.collect', return_value=collection) as collect:
            folder = Path(directory) / 'output'
            with patch('news_clustering.bot.CachedNewsE5Encoder', return_value=FixedEncoder()), redirect_stdout(StringIO()):
                code = main(['--source', 'sbs', '--limit', '2', '--output', str(folder)])
            self.assertEqual(code, 0)
            self.assertEqual(collect.call_args.kwargs['limit'], 2)
            saved = json.loads((folder / 'input.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['results'][1]['status'], 'body_not_found')
            self.assertEqual(json.loads((folder / 'representatives.json').read_text(encoding='utf-8'))['article_count'], 1)

    def test_report_escapes_news_text_refuses_non_http_links_and_uses_body_preview_label(self):
        records = [item('a', title='<script>evil()</script>', url='javascript:evil()', body='<b>원문 본문</b>')]
        with TemporaryDirectory() as directory:
            result = run_bot(records, Path(directory) / 'run', encoder=FixedEncoder())
            html = render_report(result)
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>evil()', html)
            self.assertNotIn('href="javascript:', html)
            self.assertIn('본문 미리보기', html)
            self.assertNotIn('AI 요약', html)

    def test_multiview_is_opt_in_and_saves_both_representation_archives(self):
        class TwoViewEncoder(FixedEncoder):
            def encode(self, texts):
                self.calls.append(list(texts))
                cosine = .92 if len(self.calls) == 1 else .99
                self.last_diagnostics = {'view': 'full' if len(self.calls) == 1 else 'lead'}
                return np.asarray([[1., 0.], [cosine, np.sqrt(1 - cosine ** 2)]], dtype=np.float32)
        with TemporaryDirectory() as directory, threadpool_limits(limits=2):
            folder = Path(directory) / 'run'
            result = run_bot([item('a'), item('b')], folder, encoder=TwoViewEncoder(), profile='multiview')
            self.assertEqual(result['group_count'], 1)
            self.assertEqual(result['profile'], 'multiview')
            self.assertEqual(result['multiview']['added_pair_count'], 1)
            self.assertTrue((folder / 'vectors.npz').is_file())
            self.assertTrue((folder / 'lead-vectors.npz').is_file())
            with np.load(folder / 'vectors.npz', allow_pickle=False) as archive:
                self.assertEqual(json.loads(str(archive['diagnostics'].item()))['view'], 'full')
            with np.load(folder / 'lead-vectors.npz', allow_pickle=False) as archive:
                self.assertEqual(json.loads(str(archive['diagnostics'].item()))['view'], 'lead')
            self.assertIn('도입부', (folder / 'report.html').read_text(encoding='utf-8'))

    def test_invalid_profile_is_rejected_before_output_creation(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory) / 'run'
            with self.assertRaises(ValueError):
                run_bot([item('a')], folder, encoder=FixedEncoder(), profile='unknown')
            self.assertFalse(folder.exists())

    def test_development_preset_is_explicit_and_strict_preset_remains_unchanged(self):
        class PresetEncoder(FixedEncoder):
            def encode(self, texts):
                self.calls.append(list(texts))
                cosine = .935 if len(self.calls) == 1 else .94
                return np.asarray([[1., 0.], [cosine, np.sqrt(1 - cosine ** 2)]], dtype=np.float32)
        with TemporaryDirectory() as directory, threadpool_limits(limits=2):
            strict = run_bot([item('a'), item('b')], Path(directory) / 'strict',
                             encoder=PresetEncoder(), profile='multiview')
            development = run_bot([item('a'), item('b')], Path(directory) / 'development',
                                  encoder=PresetEncoder(), profile='multiview-dev')
            self.assertEqual(strict['group_count'], 2)
            self.assertEqual(development['group_count'], 1)
            self.assertTrue(development['multiview']['development_tuned'])


if __name__ == '__main__':
    unittest.main()
