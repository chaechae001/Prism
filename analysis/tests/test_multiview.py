from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

from news_clustering.core.pipeline import ClusterConfig
from news_clustering.models import Article
from news_clustering.multiview import MultiViewConfig, cluster_multiview, lead_view


def article(key, title='은행 예금 상품 출시', **extra):
    values = {'article_id': key, 'title': title, 'body': '은행이 새 예금 상품을 출시했습니다.',
              'category': '경제', 'published_at': '2026-10-22T09:00:00Z'}
    return Article(**(values | extra))


class Encoder:
    model_id = 'offline-multiview-test'
    last_diagnostics = {'backend': 'synthetic'}

    def __init__(self, values):
        self.values, self.calls = np.asarray(values, dtype=np.float32), []

    def encode(self, texts):
        self.calls.append(list(texts))
        return self.values.copy()


def vector(cosine):
    return [cosine, np.sqrt(1 - cosine ** 2)]


def run(items, full, lead, **extra):
    with threadpool_limits(limits=2):
        return cluster_multiview(items, ClusterConfig(min_similarity=.94, min_title_similarity=.025),
                                 encoder=Encoder(full), lead_encoder=Encoder(lead), **extra)


class MultiViewTests(unittest.TestCase):
    def test_two_independent_views_rescue_a_pair_below_the_original_semantic_threshold(self):
        result = run([article('a'), article('b')], [[1, 0], vector(.92)], [[1, 0], vector(.985)])
        self.assertEqual(len(result['baseline_result']['groups']), 2)
        self.assertEqual([g['article_ids'] for g in result['groups']], [['a', 'b']])
        self.assertEqual(result['diagnostics']['multiview']['added_pair_count'], 1)
        self.assertFalse(result['groups'][0]['same_event_confirmed'])
        self.assertFalse(result['diagnostics']['accuracy_measured'])

    def test_high_full_similarity_cannot_replace_weak_lead_or_headline_evidence(self):
        items = [article('a'), article('b', title='은행 예금 상품 관련 별도 발표')]
        # Original v2 does not merge because full score is below .94.
        result = run(items, [[1, 0], vector(.92)], [[1, 0], vector(.94)])
        self.assertEqual(len(result['groups']), 2)
        self.assertEqual(result['diagnostics']['multiview']['added_pair_count'], 0)
        items[1] = article('b', title='주택 공급 계획 발표')
        result = run(items, [[1, 0], vector(.92)], [[1, 0], vector(.99)])
        self.assertEqual(len(result['groups']), 2)

    def test_original_v2_groups_remain_indivisible_and_view_disagreement_is_reviewed(self):
        result = run([article('a'), article('b')], [[1, 0], vector(.98)], [[1, 0], vector(.6)])
        self.assertEqual([g['article_ids'] for g in result['groups']], [['a', 'b']])
        self.assertEqual(result['diagnostics']['multiview']['removed_pair_count'], 0)
        self.assertGreater(result['diagnostics']['multiview']['baseline_view_disagreement_count'], 0)

    def test_complete_link_blocks_transitive_a_b_c_chain(self):
        items = [article(key) for key in 'abc']
        angles = np.deg2rad([-20, 0, 20])
        full = np.column_stack([np.cos(angles), np.sin(angles)])
        angles = np.deg2rad([-13, 0, 13])
        lead = np.column_stack([np.cos(angles), np.sin(angles)])
        result = run(items, full, lead)
        self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 2])
        self.assertTrue(all(set(g['article_ids']) != set('abc') for g in result['groups']))

    def test_missing_and_distant_publication_dates_are_not_rescued(self):
        for date in (None, '2026-10-24T09:00:00Z'):
            result = run([article('a'), article('b', published_at=date)],
                         [[1, 0], vector(.92)], [[1, 0], vector(.99)])
            self.assertEqual(len(result['groups']), 2)

    def test_one_strong_cross_pair_cannot_pull_an_entire_seed_group_into_a_merge(self):
        items = [article(key) for key in 'abc']
        full = [[1, 0, 0], [.98, np.sqrt(1 - .98 ** 2), 0], [.92, 0, np.sqrt(1 - .92 ** 2)]]
        result = run(items, full, [[1, 0], vector(.5), vector(.99)])
        self.assertIn(['a', 'b'], [g['article_ids'] for g in result['groups']])
        self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 2])

    def test_mutual_neighbours_prevent_one_sided_rescue(self):
        items = [article(key) for key in 'abc']
        # A-B are nearest to each other; C's nearest A does not reciprocate.
        full = [[1, 0, 0], [.92, np.sqrt(1 - .92 ** 2), 0], [.92, 0, np.sqrt(1 - .92 ** 2)]]
        lead = [[1, 0], vector(.999), vector(.98)]
        result = run(items, full, lead, settings=MultiViewConfig(mutual_top_k=1))
        self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 2])
        self.assertIn(['a', 'b'], [g['article_ids'] for g in result['groups']])

    def test_explicit_headline_event_conflict_blocks_only_new_connections(self):
        items = [article('a', title='CATL 배터리 교환 사업 공개'),
                 article('b', title='CATL 에너지 저장 ESS 사업 공개')]
        result = run(items, [[1, 0], vector(.92)], [[1, 0], vector(.99)])
        self.assertEqual(len(result['groups']), 2)
        self.assertTrue(any('event_target_conflict' in p['reasons']
                            for p in result['diagnostics']['multiview']['review_pairs']))

    def test_original_articles_and_exact_lead_span_are_preserved(self):
        original = article('a', body='도입부 사실입니다. ' * 100)
        before = deepcopy(original)
        view, audit = lead_view(original, 120)
        self.assertEqual(original, before)
        self.assertEqual(view.body, original.body[:120])
        self.assertEqual(audit['text'], view.body)
        self.assertEqual(audit['analysis_body_start'], 0)
        self.assertEqual(audit['analysis_body_end'], 120)
        self.assertEqual(audit['source_content_hash'], original.content_hash)

    def test_vector_identity_order_and_invalid_matrices_are_checked(self):
        full, lead = Encoder([[1, 0], vector(.92)]), Encoder([[1, 0], vector(.99)])
        items = [article('b'), article('a')]
        with threadpool_limits(limits=2):
            result = cluster_multiview(items, encoder=full, lead_encoder=lead)
        self.assertEqual(full.calls[0], [a.text for a in sorted(items, key=lambda a: a.article_id)])
        self.assertEqual(result['diagnostics']['multiview']['full_text_hashes'],
                         [sha256(text.encode()).hexdigest() for text in full.calls[0]])
        with self.assertRaises(ValueError):
            run(items, [[1, 0], vector(.92)], [[0, 0], [1, 0]])

    def test_empty_input_does_not_call_encoders_and_invalid_settings_are_rejected(self):
        full, lead = Encoder([]), Encoder([])
        result = cluster_multiview([], encoder=full, lead_encoder=lead)
        self.assertEqual(result['groups'], [])
        self.assertEqual(full.calls, [])
        self.assertEqual(lead.calls, [])
        for extra in ({'lead_similarity_min': float('nan')}, {'mutual_top_k': 0}, {'lead_characters': True}):
            with self.assertRaises(ValueError):
                MultiViewConfig(**extra)
        for invalid in ({}, [], False, 0):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                cluster_multiview([], encoder=full, lead_encoder=lead, settings=invalid)


if __name__ == '__main__':
    unittest.main()
