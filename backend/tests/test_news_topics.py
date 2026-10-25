import unittest
from backend.app.news_topics import display_category


class TopicTests(unittest.TestCase):
    def test_broad_economy_feed_routes_clear_headlines(self):
        for title,expected in [('PHP 취약점 악용한 북한 해킹조직','technology'),('한국 APEC 정보통신실무그룹 진출','technology'),
            ('산재 은폐 지시 형사 처벌 논의','society'),('국회 국정감사 질의','politics'),
            ('SK하이닉스 솔리다임 상장 검토 중단','economy'),('AI 수익성 우려 코스피 하락','economy'),
            ('관세청 원하청 단체교섭','economy')]:
            with self.subTest(title=title): self.assertEqual(display_category('economy',title),expected)

    def test_explicit_non_economy_category_and_unknown_headline_unchanged(self):
        self.assertEqual(display_category('politics','AI 기술 정책과 국회'),'politics')
        self.assertEqual(display_category('economy','뜻밖의 변화 소식'),'economy')
