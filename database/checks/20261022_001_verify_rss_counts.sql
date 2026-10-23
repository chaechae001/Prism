-- RSS migration만 적용한 직후의 기대 결과: 0 / 0 / 1 / 3 / 3 / 3.
-- RSS 데이터 저장을 시작한 뒤에는 앞 두 값이 달라질 수 있습니다.
select
  (select count(*) from private.rss_feeds) as rss_feed_count,
  (select count(*) from private.rss_items) as rss_item_count,
  (select count(*) from public.stories
   where id = 'story-001' and is_demo = true) as demo_news_count,
  (select count(*) from public.articles
   where id in ('story-001-a1', 'story-001-a2', 'story-001-a3')
     and is_demo = true) as demo_article_count,
  (select count(*) from public.story_articles
   where story_id = 'story-001') as demo_link_count,
  (select count(distinct a.publisher_id)
   from public.articles a
   join public.story_articles sa on sa.article_id = a.id
   where sa.story_id = 'story-001') as demo_publisher_count;
