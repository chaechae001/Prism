"""Behavioural regression for group-level candidate retrieval, with fixed vectors.

Synthetic vectors isolate the grouping rule; they are not an accuracy dataset.
"""
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from threadpoolctl import threadpool_limits

from news_clustering.bot import main, run_bot
from news_clustering.core.embeddings import VectorFileEncoder
from news_clustering.core.pipeline import ClusterConfig
from news_clustering.models import Article
from news_clustering.multiview import cluster_multiview, multiview_settings


def article(key, **extra):
    return Article(**({'article_id': key, 'title': '은행 예금 상품 출시',
                      'body': '은행이 새 예금 상품을 출시했습니다.', 'category': '경제',
                      'published_at': '2026-10-23T00:00:00+09:00'} | extra))


class Views:
    model_id = 'offline-seed-neighbour-fixture'

    def __init__(self, *values):
        self.values = [np.asarray(value, dtype=np.float32) for value in values]
        self.calls = 0
        self.last_diagnostics = {}

    def encode(self, texts):
        index = self.calls
        self.calls += 1
        assert index < len(self.values) and len(texts) == len(self.values[index])
        self.last_diagnostics = {'fixture_view': index, 'backend': 'synthetic'}
        return self.values[index].copy()


def fixture():
    items = [article(key) for key in 'abcde']
    full = [[1., 0.]] * 4 + [[.935, np.sqrt(1 - .935 ** 2)]]
    return items, full, [[1., 0.]] * 5


def grouped(items, full, lead, *, scope='seed_group', settings=None):
    with threadpool_limits(limits=4):
        return cluster_multiview(items, ClusterConfig(min_similarity=.94, min_title_similarity=.025),
                                 encoder=Views(full), lead_encoder=Views(lead),
                                 settings=settings or multiview_settings('multiview-dev'),
                                 neighbor_scope=scope)


class SeedNeighbourTests(unittest.TestCase):
    def test_four_article_seed_can_accept_a_matching_article_without_relaxing_pair_gates(self):
        items, full, lead = fixture()
        old = grouped(items, full, lead, scope='article')
        result = grouped(items, full, lead)
        self.assertEqual(sorted(g['article_count'] for g in old['groups']), [1, 4])
        self.assertEqual(sorted(g['article_count'] for g in result['baseline_result']['groups']), [1, 4])
        self.assertEqual([g['article_ids'] for g in result['groups']], [list('abcde')])
        self.assertEqual(result['diagnostics']['multiview']['added_pair_count'], 4)
        self.assertFalse(result['groups'][0]['same_event_confirmed'])

    def test_two_large_seeds_can_join_without_article_top_k_size_cap(self):
        full = [[1., 0.]] * 4 + [[.935, np.sqrt(1 - .935 ** 2)]] * 4
        result = grouped([article(key) for key in 'abcdefgh'], full, [[1., 0.]] * 8)
        self.assertEqual(sorted(g['article_count'] for g in result['baseline_result']['groups']), [4, 4])
        self.assertEqual([g['article_ids'] for g in result['groups']], [list('abcdefgh')])

    def test_one_weak_member_blocks_a_whole_seed_merge(self):
        items, full, lead = fixture()
        lead[3] = [.5, np.sqrt(.75)]
        result = grouped(items, full, lead)
        self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 4])
        self.assertEqual(result['diagnostics']['multiview']['added_pair_count'], 0)
        cross = next(row for row in result['diagnostics']['multiview']['review_pairs']
                     if row['article_ids'] == ['a', 'e'])
        self.assertFalse(cross['eligible_new_connection'])
        self.assertIn('seed_group_cross_pair_failed', cross['reasons'])

    def test_group_neighbours_rank_the_weakest_pair_rather_than_the_best_member(self):
        items = [article(key) for key in 'abcdef']
        radius = np.sqrt(1 - .935 ** 2)
        full = [[1., 0., 0.]] * 4 + [[.935, radius, 0.], [.935, 0., radius]]
        angles = np.deg2rad([-10, -4, 2, 8, 10, -1])
        lead = np.column_stack([np.cos(angles), np.sin(angles)])
        result = grouped(items, full, lead, settings=replace(multiview_settings('multiview-dev'), mutual_top_k=1))
        # e has the closest single member (d), but f fits every seed member better.
        self.assertEqual(sorted(g['article_ids'] for g in result['groups']), [list('abcdf'), ['e']])

    def test_mutual_group_neighbours_still_block_one_sided_connections(self):
        radius = np.sqrt(1 - .935 ** 2)
        full = [[1., 0., 0.], [.935, radius, 0.], [.935, 0., radius]]
        lead = [[1., 0.], [.999, np.sqrt(1 - .999 ** 2)], [.98, np.sqrt(1 - .98 ** 2)]]
        result = grouped([article(key) for key in 'abc'], full, lead,
                         settings=replace(multiview_settings('multiview-dev'), mutual_top_k=1))
        self.assertEqual(sorted(g['article_ids'] for g in result['groups']), [['a', 'b'], ['c']])

    def test_group_gate_does_not_turn_a_b_c_into_a_transitive_chain(self):
        full_angles, lead_angles = np.deg2rad([-20, 0, 20]), np.deg2rad([-10, 0, 10])
        result = grouped([article(key) for key in 'abc'],
                         np.column_stack([np.cos(full_angles), np.sin(full_angles)]),
                         np.column_stack([np.cos(lead_angles), np.sin(lead_angles)]))
        self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 2])

    def test_missing_or_distant_dates_block_large_seed_rescue(self):
        for date in (None, '2026-10-25T00:00:00+09:00'):
            items, full, lead = fixture()
            items[-1] = replace(items[-1], published_at=date)
            result = grouped(items, full, lead)
            self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 4])

    def test_event_target_conflict_blocks_large_seed_rescue(self):
        items, full, lead = fixture()
        items = [replace(row, title='CATL 배터리 교환 사업 공개') for row in items]
        items[-1] = replace(items[-1], title='CATL 에너지 저장 ESS 사업 공개')
        result = grouped(items, full, lead)
        self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 4])
        self.assertTrue(any('event_target_conflict' in row['reasons']
                            for row in result['diagnostics']['multiview']['review_pairs']))

    def test_input_order_does_not_change_seed_selection_and_sources_are_unchanged(self):
        items, full, lead = fixture()
        original = deepcopy(items)
        first = grouped(items, full, lead)
        second = grouped(list(reversed(items)), full, lead)
        self.assertEqual(first, second)
        self.assertEqual(items, original)

    def test_invalid_scope_fails_before_encoding_and_empty_input_needs_no_vectors(self):
        for scope in ('unknown', None, {}, [], True):
            encoder = Views()
            with self.assertRaises(ValueError):
                cluster_multiview([article('a')], encoder=encoder, lead_encoder=encoder, neighbor_scope=scope)
            self.assertEqual(encoder.calls, 0)
        empty = grouped([], [], [])
        self.assertEqual(empty['groups'], [])
        self.assertEqual(empty['diagnostics']['multiview']['feasible_seed_group_pair_count'], 0)

    def test_bot_group_profile_saves_raw_bodies_two_views_and_one_representative(self):
        items, full, lead = fixture()
        raw = [row.to_dict() | {'rss_guid': 'guid-' + row.article_id,
                                'rights': {'license_status': 'unknown', 'allowed_uses': []}} for row in items]
        original = deepcopy(raw)
        with TemporaryDirectory() as directory:
            folder = Path(directory) / 'group'
            exported = run_bot(raw, folder, encoder=Views(full, lead), profile='multiview-group')
            self.assertEqual(exported['group_count'], 1)
            self.assertEqual(exported['groups'][0]['representative']['article_id'], 'a')
            self.assertEqual(exported['groups'][0]['representative']['metadata']['rss_guid'], 'guid-a')
            self.assertEqual(exported['groups'][0]['representative']['body'], raw[0]['body'])
            self.assertEqual(exported['multiview']['neighbor_scope'], 'seed_group')
            self.assertTrue(exported['multiview']['development_tuned'])
            self.assertFalse(exported['accuracy_measured'])
            self.assertEqual(exported['shared_database_writes'], 0)
            full_archive, lead_archive = VectorFileEncoder(folder / 'vectors.npz'), VectorFileEncoder(folder / 'lead-vectors.npz')
            self.assertEqual(full_archive.last_diagnostics['fixture_view'], 0)
            self.assertEqual(lead_archive.last_diagnostics['fixture_view'], 1)
            self.assertEqual(raw, original)
            self.assertIn('군집 단위', (folder / 'report.html').read_text(encoding='utf-8'))

    def test_cli_group_profile_and_empty_group_run_are_supported_without_collection(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.json'
            source.write_text(json.dumps([article('a').to_dict()], ensure_ascii=False), encoding='utf-8')
            with patch('news_clustering.bot.collect', side_effect=AssertionError('Collection forbidden')), \
                 patch('news_clustering.bot.CachedNewsE5Encoder', return_value=Views([[1., 0.]], [[1., 0.]])), \
                 redirect_stdout(StringIO()):
                code = main(['--input', str(source), '--output', str(root / 'cli'), '--profile', 'multiview-group'])
            self.assertEqual(code, 0)
            saved = json.loads((root / 'cli/representatives.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['profile'], 'multiview-group')
            with patch('news_clustering.bot.CachedNewsE5Encoder', side_effect=AssertionError('Model forbidden')):
                empty = run_bot([], root / 'empty', profile='multiview-group')
            self.assertEqual(empty['status'], 'no_eligible_articles')
            self.assertEqual(empty['multiview']['neighbor_scope'], 'seed_group')
