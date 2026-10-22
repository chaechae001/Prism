-- 가상 XML 저장 후 실행하는 읽기 전용 확인 쿼리입니다. 변경 작업은 없습니다.
-- 이 쿼리의 RSS 개수는 아래 네 개의 가상 피드만 대상으로 합니다.
with demo_feeds as (
  select id from private.rss_feeds
  where id in ('feed-demo-economy', 'feed-demo-industry',
               'feed-demo-politics', 'feed-demo-science')
), demo_items as (
  select i.* from private.rss_items i join demo_feeds f on f.id = i.feed_id
)
select
  (select count(*) from demo_feeds) as rss_feed_count,
  (select count(*) from demo_items) as rss_item_count,
  (select count(distinct article_id) from demo_items) as rss_article_count,
  (select count(*) from demo_items
   where published_at is null and article_id is null and parse_status = 'partial')
    as rss_date_unknown_count,
  (select count(*) from public.stories where id = 'story-001' and is_demo = true)
    as original_news_count,
  (select count(*) from public.articles
   where id in ('story-001-a1', 'story-001-a2', 'story-001-a3') and is_demo = true)
    as original_article_count,
  (select count(*) from public.story_articles where story_id = 'story-001')
    as original_link_count;

-- 예상 결과: 4 / 5 / 4 / 1 / 1 / 3 / 3

-- 날짜 오류가 있는 원본 항목은 삭제하지 않고 비공개 테이블에 남겨둡니다.
select feed_id, source_item_id, title, parse_status, source_published_raw,
       published_at, article_id, collected_at, last_seen_at
from private.rss_items
where feed_id in ('feed-demo-economy', 'feed-demo-industry',
                  'feed-demo-politics', 'feed-demo-science')
order by feed_id, item_key;
