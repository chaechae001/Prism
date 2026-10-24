"""Source evidence can assist a strict bridge, never replace all pair checks."""
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
from news_clustering.core.pipeline import ClusterConfig
from news_clustering.models import Article
from news_clustering.multiview import cluster_multiview, multiview_settings


class Encoder:
    model_id = 'offline-source-anchor-fixture'

    def __init__(self, *views):
        self.views = [np.asarray(values, dtype=np.float32) for values in views]
        self.calls, self.last_diagnostics = 0, {}

    def encode(self, texts):
        view = self.views[self.calls]
        self.last_diagnostics = {'fixture_view': self.calls}
        self.calls += 1
        assert len(texts) == len(view)
        return view.copy()


def fixture():
    first = '한국은행은 오늘(23일) 금융통화위원회를 열고 기준금리를 연 3.00%로 동결했습니다. '
    titles = ['한은 기준금리 동결 만장일치 배경 설명', '한은 기준금리 연 3% 동결 만장일치 결정',
              '한은 기준금리 동결 만장일치 총재 설명']
    suffixes = ['금통위는 경제 위험을 점검할 필요가 있다고 밝혔습니다.',
                '위원들이 모두 같은 판단을 내렸다고 설명했습니다.',
                '총재는 결정 이후 기자간담회에서 배경을 설명했습니다.']
    items = [Article(article_id=key, title=title, body=first + suffix, category='경제',
                     published_at='2026-10-23T09:00:00+09:00', url='https://example.org/' + key)
             for key, title, suffix in zip('abc', titles, suffixes)]
    full = [[1., 0., 0.], [.96, .28, 0.], [.935, .08, np.sqrt(1 - .935 ** 2 - .08 ** 2)]]
    second = np.sqrt(1 - .98 ** 2)
    y = (.916 - .98 * .95) / second
    lead = [[1., 0., 0.], [.98, second, 0.], [.95, y, np.sqrt(1 - .95 ** 2 - y ** 2)]]
    return items, full, lead


def run(items, full, lead, enabled=True):
    with threadpool_limits(limits=4):
        return cluster_multiview(items, ClusterConfig(min_similarity=.94, min_title_similarity=.025),
            encoder=Encoder(full), lead_encoder=Encoder(lead), settings=multiview_settings('multiview-dev'),
            neighbor_scope='seed_group', anchor_rescue=enabled)


class AnchorBridgeTests(unittest.TestCase):
    def test_explicit_decision_corroborates_weak_pair_only_alongside_a_strict_bridge(self):
        items, full, lead = fixture()
        before = run(items, full, lead, False)
        after = run(items, full, lead)
        self.assertEqual(sorted(g['article_count'] for g in before['groups']), [1, 2])
        self.assertEqual([g['article_ids'] for g in after['groups']], [list('abc')])
        detail = after['diagnostics']['multiview']
        self.assertEqual(detail['added_pair_count'], 2)
        self.assertEqual(detail['anchor_rescue']['grouped_relaxed_pair_count'], 1)
        weak = next(row for row in detail['review_pairs'] if row['article_ids'] == ['b', 'c'])
        self.assertEqual(weak['connection_route'], 'source_anchor')
        self.assertTrue(weak['grouped_together'])
        self.assertFalse(after['groups'][0]['same_event_confirmed'])

    def test_matching_anchors_alone_cannot_join_two_singletons(self):
        items, _, _ = fixture()
        values = [[1., 0.], [.92, np.sqrt(1 - .92 ** 2)]]
        result = run(items[:2], values, values)
        self.assertEqual(len(result['groups']), 2)
        pair = result['diagnostics']['multiview']['review_pairs'][0]
        self.assertIn('seed_group_no_strict_bridge', pair['reasons'])
        self.assertEqual(result['diagnostics']['multiview']['anchor_rescue']['grouped_relaxed_pair_count'], 0)

    def test_missing_source_anchor_cannot_pull_a_weak_member_of_a_seed(self):
        items, full, lead = fixture()
        items[1] = replace(items[1], body=items[1].body.replace('오늘(23일)', '최근'))
        result = run(items, full, lead)
        self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 2])

    def test_known_rate_conflict_blocks_even_a_new_strict_connection(self):
        items, full, lead = fixture()
        items[2] = replace(items[2], body=items[2].body.replace('3.00%', '3.25%'))
        result = run(items, full, lead)
        self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 2])
        self.assertTrue(any('source_anchor_rate_percent_conflict' in row['reasons']
                            for row in result['diagnostics']['multiview']['review_pairs']))

    def test_shared_body_with_different_headlines_is_a_review_flag_and_not_rescue_evidence(self):
        items, full, lead = fixture()
        items[2] = replace(items[2], body=items[0].body)
        result = run(items, full, lead)
        self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 2])
        audit = result['diagnostics']['multiview']['shared_summary_audit']
        self.assertEqual(audit['article_ids_requiring_review'], ['a', 'c'])
        self.assertFalse(audit['equality_is_same_event_proof'])

    def test_anchor_edges_still_cannot_form_a_transitive_chain(self):
        items, _, _ = fixture()
        radius = np.sqrt(1 - .935 ** 2)
        y = (.935 - .935 * .92) / radius
        full = [[1., 0., 0.], [.935, radius, 0.], [.92, y, np.sqrt(1 - .92 ** 2 - y ** 2)]]
        result = run(items, full, [[1., 0.]] * 3)
        self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 2])

    def test_known_time_gate_and_numeric_floor_remain_required(self):
        for change in ('missing_time', 'distant_time', 'weak_full'):
            items, full, lead = fixture()
            if change == 'missing_time':
                items[-1] = replace(items[-1], published_at=None)
            elif change == 'distant_time':
                items[-1] = replace(items[-1], published_at='2026-10-25T09:00:00+09:00')
            else:
                full[-1] = [.80, 0., .60]
            result = run(items, full, lead)
            self.assertEqual(sorted(g['article_count'] for g in result['groups']), [1, 2])

    def test_flag_validation_empty_run_and_original_input_preservation(self):
        for flag, scope in ((None, 'seed_group'), (1, 'seed_group'), (True, 'article')):
            encoder = Encoder()
            with self.assertRaises(ValueError):
                cluster_multiview([], encoder=encoder, lead_encoder=encoder,
                                 neighbor_scope=scope, anchor_rescue=flag)
            self.assertEqual(encoder.calls, 0)
        empty = run([], [], [])
        self.assertEqual(empty['groups'], [])
        self.assertEqual(empty['diagnostics']['multiview']['anchor_rescue']['grouped_relaxed_pair_count'], 0)
        items, full, lead = fixture()
        original = deepcopy(items)
        run(items, full, lead)
        self.assertEqual(items, original)

    def test_bot_profile_preserves_metadata_marks_shared_summaries_and_cli_accepts_it(self):
        items, full, lead = fixture()
        items[2] = replace(items[2], body=items[0].body)
        raw = [row.to_dict() | {'rss_guid': 'guid-' + row.article_id} for row in items]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_bot(raw, root / 'run', profile='multiview-anchor', encoder=Encoder(full, lead))
            self.assertEqual(result['quality_audit']['shared_summary_cluster_count'], 1)
            self.assertTrue(all(group['quality_review_required'] for group in result['groups']))
            self.assertEqual(result['groups'][0]['representative']['metadata']['rss_guid'], 'guid-a')
            self.assertIn('동일한 본문', (root / 'run/report.html').read_text(encoding='utf-8'))
            source = root / 'input.json'
            source.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
            with patch('news_clustering.bot.collect', side_effect=AssertionError('Collection forbidden')), \
                 patch('news_clustering.bot.CachedNewsE5Encoder', return_value=Encoder(full, lead)), \
                 redirect_stdout(StringIO()):
                code = main(['--input', str(source), '--output', str(root / 'cli'), '--profile', 'multiview-anchor'])
            self.assertEqual(code, 0)
            with patch('news_clustering.bot.CachedNewsE5Encoder', side_effect=AssertionError('Model forbidden')):
                empty = run_bot([], root / 'empty', profile='multiview-anchor')
            self.assertEqual(empty['quality_audit']['shared_summary_cluster_count'], 0)
