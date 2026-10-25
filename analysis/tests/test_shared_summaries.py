from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from itertools import permutations
import unittest

from news_clustering.core.shared_summaries import audit_shared_summaries
from news_clustering.models import Article


def article(article_id, title, body, *, source_id='sbs-03'):
    return Article(
        article_id, title, body, '사회', '2026-10-22T07:00:00Z',
        publisher='SBS', url=f'https://example.test/news/{article_id}',
        source_id=source_id, body_kind='publisher_html',
        source_notice='Source notice retained for source review.',
    )


class SharedSummaryTests(unittest.TestCase):
    def test_identical_body_with_different_headlines_is_review_only(self):
        originals = [article('b', '법원 항소심 선고', 'Shared broadcast summary.'),
                     article('a', '정부 예산안 발표', 'Shared broadcast summary.')]

        result = audit_shared_summaries(originals)

        self.assertEqual(result['method'], 'identical-cleaned-body-divergent-headlines/v1')
        self.assertEqual(result['article_ids_requiring_review'], ['a', 'b'])
        self.assertIs(result['equality_is_same_event_proof'], False)
        self.assertIs(result['human_verified'], False)
        self.assertEqual(len(result['clusters']), 1)
        cluster = result['clusters'][0]
        self.assertEqual(cluster['analysis_body_sha256'], sha256(b'Shared broadcast summary.').hexdigest())
        self.assertEqual(cluster['analysis_body_characters'], 25)
        self.assertEqual(cluster['article_ids'], ['a', 'b'])
        self.assertEqual(cluster['article_count'], 2)
        self.assertEqual(cluster['titles'], [
            {'article_id': 'a', 'title': '정부 예산안 발표'},
            {'article_id': 'b', 'title': '법원 항소심 선고'},
        ])
        self.assertEqual(cluster['source_content_hashes'], {
            original.article_id: original.content_hash for original in originals
        })
        self.assertEqual(cluster['reason'], 'identical_cleaned_body_different_headlines')
        self.assertIs(cluster['requires_review'], True)
        self.assertIs(cluster['human_verified'], False)
        self.assertNotIn('same_event', cluster)

    def test_headline_case_unicode_punctuation_and_whitespace_do_not_create_review(self):
        titles = ['ＡＩ  정책 발표!', 'ai 정책 발표', '“AI” 정책\t발표…']
        originals = [article(str(i), title, 'A shared report.') for i, title in enumerate(titles)]

        result = audit_shared_summaries(originals)

        self.assertEqual(result['clusters'], [])
        self.assertEqual(result['article_ids_requiring_review'], [])

    def test_distinct_bodies_and_single_articles_are_not_flagged(self):
        originals = [article('a', '금리 동결', 'Rate held.'),
                     article('b', '금리 인상', 'Rate raised.'),
                     article('c', '금리 유지', 'Rate held. ')]

        result = audit_shared_summaries(originals)

        self.assertEqual(result['clusters'], [])
        self.assertEqual(result['article_ids_requiring_review'], [])

    def test_analysis_cleanup_can_expose_shared_body_without_losing_sources(self):
        originals = [article('a', '정부 예산안 발표', 'Shared synopsis. (사진=연합뉴스)'),
                     article('b', '법원 항소심 선고', 'Shared synopsis. ※ 자세한 내용은 동영상으로 확인하실 수 있습니다.')]

        result = audit_shared_summaries(originals)

        cluster = result['clusters'][0]
        self.assertEqual(cluster['article_ids'], ['a', 'b'])
        self.assertEqual(cluster['analysis_body_characters'], 16)
        self.assertEqual(cluster['analysis_body_sha256'], sha256(b'Shared synopsis.').hexdigest())
        self.assertEqual(len(cluster['source_content_hashes']), 2)
        self.assertNotEqual(cluster['source_content_hashes']['a'], cluster['source_content_hashes']['b'])

    def test_cleaned_headline_is_used_but_original_title_is_reported(self):
        originals = [article('a', '[여담야담] 금리 동결', 'Same synopsis.'),
                     article('b', '금리 동결', 'Same synopsis.')]
        self.assertEqual(audit_shared_summaries(originals)['clusters'], [])

        originals.append(article('c', '[주영진 뉴스브리핑] 예산 발표', 'Same synopsis.'))
        cluster = audit_shared_summaries(originals)['clusters'][0]
        self.assertEqual(cluster['titles'], [
            {'article_id': 'a', 'title': '[여담야담] 금리 동결'},
            {'article_id': 'b', 'title': '금리 동결'},
            {'article_id': 'c', 'title': '[주영진 뉴스브리핑] 예산 발표'},
        ])

    def test_empty_whitespace_and_metadata_only_bodies_are_skipped(self):
        metadata = "'SBS <주영진 뉴스브리핑>' ■ 진행 : 주영진 앵커"
        originals = [article(str(i), title, body)
                     for i, (title, body) in enumerate([
                         ('정부 예산안', ''), ('법원 선고', ''),
                         ('금리 동결', ' \t\n'), ('금리 인상', ' \t\n'),
                         ('정책 발표', metadata), ('항소심 선고', metadata),
                     ])]

        result = audit_shared_summaries(originals)

        self.assertEqual(result['clusters'], [])
        self.assertEqual(result['article_ids_requiring_review'], [])

    def test_all_members_of_divergent_group_keep_their_distinct_ids(self):
        originals = [article('c', '금리 동결', 'Shared synopsis.'),
                     article('a', '금리 동결', 'Shared synopsis.'),
                     article('b', '예산 발표', 'Shared synopsis.')]

        cluster = audit_shared_summaries(originals)['clusters'][0]

        self.assertEqual(cluster['article_ids'], ['a', 'b', 'c'])
        self.assertEqual(cluster['article_count'], 3)
        self.assertEqual(len(cluster['titles']), 3)
        self.assertEqual(set(cluster['source_content_hashes']), {'a', 'b', 'c'})

    def test_result_is_deterministic_under_input_order_changes(self):
        originals = [article('d', '금리 동결', 'First synopsis.'),
                     article('b', '예산 발표', 'First synopsis.'),
                     article('c', '법원 선고', 'Second synopsis.'),
                     article('a', '국회 질의', 'Second synopsis.')]
        expected = audit_shared_summaries(originals)

        for order in permutations(originals):
            self.assertEqual(audit_shared_summaries(list(order)), expected)
        self.assertEqual(expected['article_ids_requiring_review'], ['a', 'b', 'c', 'd'])
        self.assertEqual(len(expected['clusters']), 2)

    def test_original_body_identity_and_metadata_remain_unchanged(self):
        originals = [article('a', '[여담야담] 금리 동결', 'Shared synopsis. (사진=연합뉴스)'),
                     article('b', '예산 발표', 'Shared synopsis. (사진=AP)')]
        before = deepcopy([asdict(original) for original in originals])
        hashes = [original.content_hash for original in originals]

        audit_shared_summaries(originals)

        self.assertEqual([asdict(original) for original in originals], before)
        self.assertEqual([original.content_hash for original in originals], hashes)
        self.assertIsNot(originals[0], originals[1])

    def test_empty_input_has_no_review_candidates(self):
        result = audit_shared_summaries([])
        self.assertEqual(result['clusters'], [])
        self.assertEqual(result['article_ids_requiring_review'], [])

    def test_duplicate_ids_are_rejected_without_silently_losing_source_hashes(self):
        first = article('dup', '금리 동결', 'Shared synopsis.')
        variants = [
            first,
            replace(first, title='예산 발표', url='https://other.test/news/second'),
            replace(first, title='법원 선고', body='Different source body.'),
            replace(first, title='의회 질의', body=''),
        ]

        for second in variants:
            with self.subTest(second=second):
                with self.assertRaisesRegex(ValueError, r'duplicate article_id.*dup'):
                    audit_shared_summaries([first, second])


if __name__ == '__main__':
    unittest.main()
