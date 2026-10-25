from dataclasses import asdict
import unittest

from news_clustering.core.analysis_text import prepare_article
from news_clustering.models import Article


def article(body, title='금융위원장, 가상자산 과세 검토', source='sbs-02'):
    return Article('one', title, body, '경제', '2026-10-22T10:00:00+09:00',
                   publisher='SBS', source_id=source, body_kind='publisher_html')


class AnalysisTextTests(unittest.TestCase):
    def assert_traceable(self, result):
        for span in result.audit['removed_spans']:
            raw = getattr(result.original, span['field'])
            self.assertEqual(raw[span['start']:span['end']], span['text'])

    def test_photo_credit_removed_but_caption_facts_and_negation_are_retained(self):
        caption = '▲ 금융위원장이 국회에서 의원 질의에 답하고 있다.'
        original = article(caption + ' 과세 유예는 확정되지 않았습니다. (사진=연합뉴스)')
        before = asdict(original)
        result = prepare_article(original)
        self.assertEqual(result.article.body, caption + ' 과세 유예는 확정되지 않았습니다.')
        self.assertEqual(asdict(original), before)
        self.assertEqual(result.audit['original_content_hash'], original.content_hash)
        self.assert_traceable(result)

    def test_bullet_that_contains_news_is_retained(self):
        original = article('▲ 한국은행은 기준금리를 동결하지 않았습니다. 인상안을 의결했습니다.')
        result = prepare_article(original)
        self.assertEqual(result.article, original)
        self.assertIn('unparsed_leading_caption_marker', result.audit['warnings'])

    def test_multiline_and_single_line_broadcast_headers_keep_the_actual_discussion(self):
        header = ("[주영진 뉴스브리핑] 인터뷰를 인용 보도할 때는 프로그램명 'SBS <주영진 뉴스브리핑>'을 "
                  '정확히 밝혀주시기 바랍니다. 저작권은 SBS에 있습니다. '
                  '■ 방송 : SBS <주영진 뉴스브리핑> 월~금 (14:00~15:20) '
                  '■ 진행 : 주영진 앵커 ■ 대담 : 홍길동 교수 -------------------------------------------- ')
        discussion = '● 법원 판결 홍길동 / 교수 "무죄가 아닙니다. 항소가 남았습니다."'
        footer = ' ※ 자세한 내용은 동영상으로 확인하실 수 있습니다.'
        for value in (header + discussion + footer, header.replace(' ■', '\n■') + discussion + footer):
            with self.subTest(value=value):
                result = prepare_article(article(value, title='[여담야담] 항소심 선고'))
                self.assertEqual(result.article.body, discussion)
                self.assertEqual(result.article.title, '항소심 선고')
                self.assert_traceable(result)

    def test_truncated_rss_preserves_ambiguous_guest_or_event_tail(self):
        body = "'SBS <주영진 뉴스브리핑>' ■ <주영진 뉴스브리핑> ■ 진행 : 주영진 앵커■ 박용진 규제합…"
        result = prepare_article(article(body))
        self.assertEqual(result.article.body, '■ 박용진 규제합…')
        self.assertIn('unparsed_broadcast_tail', result.audit['warnings'])
        self.assert_traceable(result)

    def test_substantive_broadcast_tail_and_spoken_negation_survive(self):
        for tail in ('■ 김철수 무죄선고…', '■ 박용진 과세반대…'):
            result = prepare_article(article("'SBS <주영진 뉴스브리핑>' ■ 진행 : 주영진 앵커 " + tail))
            self.assertEqual(result.article.body, tail)
        for statement in ('▲ 장관은 과세 유예는 없다고 발언하고 있다.',
                          '▲ 장관은 "유예는 없다"며 발언하고 있다.',
                          '▲ 장관이 과세에 반대하며 발언하고 있다.',
                          '▲ 장관이 과세 연기를 거부하며 발언하고 있다.',
                          '▲ 장관이 과세 유예를 못 하겠다는 입장을 전하며 발언하고 있다.'):
            original = article(statement + ' 시행은 내년이다.')
            self.assertEqual(prepare_article(original).article, original)

    def test_known_program_metadata_with_no_trailing_news_can_be_empty(self):
        result = prepare_article(article("'SBS <주영진 뉴스브리핑>' ■ 진행 : 주영진 앵커"))
        self.assertEqual(result.article.body, '')
        self.assertIn('title_only_after_cleanup', result.audit['warnings'])

    def test_combined_boundaries_are_idempotent_and_all_spans_are_original_offsets(self):
        body = ('▲ 총재가 의사봉을 두드리고 있다. ▲ 위원장이 질의에 답하고 있다. '
                '금리는 3.0%입니다. ※ 자세한 내용은 동영상으로 확인하실 수 있습니다. (사진=연합뉴스)')
        first = prepare_article(article(body))
        self.assertEqual(first.article.body, '▲ 총재가 의사봉을 두드리고 있다. ▲ 위원장이 질의에 답하고 있다. 금리는 3.0%입니다.')
        self.assertEqual(prepare_article(first.article).article, first.article)
        self.assert_traceable(first)

    def test_metadata_only_boundaries_reach_one_fixed_point_in_both_orders(self):
        prefix = "'SBS <주영진 뉴스브리핑>' ■ 진행 : 주영진 앵커"
        for suffix in (' (사진=연합뉴스)', ' ※ 자세한 내용은 동영상으로 확인하실 수 있습니다.',
                       ' ※ 자세한 내용은 동영상으로 확인하실 수 있습니다. (사진=연합뉴스)'):
            result = prepare_article(article(prefix + suffix))
            self.assertEqual(result.article.body, '')
            self.assertEqual(prepare_article(result.article).article, result.article)
            self.assert_traceable(result)

    def test_event_bullet_in_description_is_never_dropped_as_metadata(self):
        body = "'SBS <주영진 뉴스브리핑>' ■ 진행 : 주영진 앵커 ● 항소심에서 무죄 선고…"
        self.assertEqual(prepare_article(article(body)).article.body, body)

    def test_unknown_source_and_unmarked_body_are_unchanged(self):
        for original in (article('▲ 장관이 의사봉을 두드리고 있다. 동결했습니다.', source='other'),
                         article('국회에서 질의에 답하고 있다. 과세 계획은 미정입니다.'),
                         article('사진이라는 단어와 방송 진행자를 다룬 기사입니다.'),
                         article('')):
            self.assertEqual(prepare_article(original).article, original)

    def test_cleanup_is_idempotent_and_identifiers_dates_and_provenance_survive(self):
        original = article('▲ 총재가 의사봉을 두드리고 있다. 기준금리 3.0%를 유지했습니다.')
        first = prepare_article(original)
        second = prepare_article(first.article)
        self.assertEqual(first.article, second.article)
        self.assertEqual(second.audit['removed_spans'], [])
        for name in ('article_id', 'published_at', 'publisher', 'source_id', 'body_kind'):
            self.assertEqual(getattr(first.article, name), getattr(original, name))


if __name__ == '__main__':
    unittest.main()
