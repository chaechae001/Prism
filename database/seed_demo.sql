-- 개발용 가상 데이터 입력: 뉴스 1개, 기사 3개, 언론사 3개.
-- 출처: contracts/fixtures.json의 story-001. 기사 제목·요약·관점은 원본 값을 사용합니다.
-- schema.draft.sql의 테이블 생성 및 추가 저장 항목 반영 후 실행합니다.
-- 같은 ID가 있으면 아래 데모 값으로 갱신합니다. 다른 ID의 데이터는 삭제하지 않습니다.
-- 실제 수집·군집분석·LLM 실행 또는 실제 언론사의 이용 권한 검증 결과가 아닙니다.

begin;
set local standard_conforming_strings = on;

-- 1. 언론사를 먼저 저장합니다. 기사가 publisher_id로 참조하기 때문입니다.
-- group_id는 가상 테스트용 식별자입니다. 실제 언론사 소유 그룹을 나타내지 않습니다.
insert into public.publishers (id, name, group_id)
values
  ('p-01', '데모 일보', 'demo-group-p-01'),
  ('p-02', '데모 경제', 'demo-group-p-02'),
  ('p-03', '데모 시민', 'demo-group-p-03')
on conflict (id) do update set
  name = excluded.name,
  group_id = excluded.group_id;

-- 2. 뉴스와 요약을 저장합니다. API 응답의 필드 이름은 변경하지 않습니다.
-- summary.status는 summary_status 열에 저장하고, 나머지는 summary JSON에 보존합니다.
-- API에서는 두 값을 합쳐 기존 summary 구조로 반환해야 합니다.
-- published_at은 공개 여부를 제어하는 시각이며, updated_at과 별개입니다.
insert into public.stories (
  id, title, dek, category, keywords, visual, public_interest, is_demo,
  summary_status, summary, perspectives, label_status,
  updated_at, published_at, retracted_at
)
values (
  'story-001',
  'AI가 바꾸는 일터, 생산성 너머의 질문들',
  '생산성의 기회와 일자리 전환의 과제를 함께 읽습니다.',
  'technology',
  array['AI', '노동', '생산성']::text[],
  'chip',
  0.97,
  true,
  'ready',
  $summary_json$
{
  "bullets": [
    {
      "text": "생산성의 기회와 일자리 전환의 과제를 함께 읽습니다.",
      "article_ids": [
        "story-001-a1",
        "story-001-a2"
      ]
    },
    {
      "text": "가상 자료에서는 기대 효과와 실행 비용을 서로 다른 쟁점으로 다룹니다.",
      "article_ids": [
        "story-001-a1",
        "story-001-a3"
      ]
    },
    {
      "text": "구체적인 효과는 후속 자료와 당사자 의견을 확인해야 합니다.",
      "article_ids": [
        "story-001-a2"
      ]
    }
  ],
  "unknowns": [
    "실제 보도가 아닌 UI 개발용 가상 자료입니다."
  ],
  "model_version": "fixture-only",
  "prompt_version": "demo-v1"
}
$summary_json$::jsonb,
  $perspectives_json$
[
  {
    "label": "기회와 기대",
    "text": "도입으로 얻을 수 있는 편익과 새로운 가능성을 강조합니다.",
    "article_ids": [
      "story-001-a1"
    ]
  },
  {
    "label": "현장의 과제",
    "text": "비용 부담과 실행 과정에서 소외될 수 있는 집단을 살펴봅니다.",
    "article_ids": [
      "story-001-a2"
    ]
  },
  {
    "label": "제도와 실행",
    "text": "단계적인 시행과 성과 검증을 위한 조건에 주목합니다.",
    "article_ids": [
      "story-001-a3"
    ]
  }
]
$perspectives_json$::jsonb,
  'demo',
  '2026-10-21T13:50:00+09:00'::timestamptz,
  '2026-10-21T13:50:00+09:00'::timestamptz,
  null
)
on conflict (id) do update set
  title = excluded.title,
  dek = excluded.dek,
  category = excluded.category,
  keywords = excluded.keywords,
  visual = excluded.visual,
  public_interest = excluded.public_interest,
  is_demo = excluded.is_demo,
  summary_status = excluded.summary_status,
  summary = excluded.summary,
  perspectives = excluded.perspectives,
  label_status = excluded.label_status,
  updated_at = excluded.updated_at,
  published_at = excluded.published_at,
  retracted_at = excluded.retracted_at;

-- 3. 관련 기사 3개를 저장합니다. 원문 본문은 포함하지 않습니다.
-- API의 url 값은 DB의 canonical_url 열에 저장합니다.
-- publish_allowed=true는 이 가상 메타데이터를 개발 화면에 표시하기 위한 값입니다.
insert into public.articles (
  id, publisher_id, canonical_url, title, framing, published_at,
  is_demo, publish_allowed
)
values
  ('story-001-a1', 'p-01', 'https://example.com/demo/story-001/a1', '[가상 기사] AI가 바꾸는 일터, 생산성 너머의 질문들 — 기회와 기대', '기회와 기대', '2026-10-21T09:00:00+09:00'::timestamptz, true, true),
  ('story-001-a2', 'p-02', 'https://example.com/demo/story-001/a2', '[가상 기사] AI가 바꾸는 일터, 생산성 너머의 질문들 — 현장의 과제', '현장의 과제', '2026-10-21T09:10:00+09:00'::timestamptz, true, true),
  ('story-001-a3', 'p-03', 'https://example.com/demo/story-001/a3', '[가상 기사] AI가 바꾸는 일터, 생산성 너머의 질문들 — 제도와 실행', '제도와 실행', '2026-10-21T09:20:00+09:00'::timestamptz, true, true)
on conflict (id) do update set
  publisher_id = excluded.publisher_id,
  canonical_url = excluded.canonical_url,
  title = excluded.title,
  framing = excluded.framing,
  published_at = excluded.published_at,
  is_demo = excluded.is_demo,
  publish_allowed = excluded.publish_allowed;

-- 4. 뉴스와 기사를 연결합니다.
-- same_event_verified=true는 이 가상 입력 묶음을 수동 확인했다는 테스트 설정입니다.
-- 실제 분석 결과를 자동으로 검증 완료 처리하는 로직으로 사용하지 않습니다.
insert into public.story_articles (story_id, article_id, same_event_verified)
values
  ('story-001', 'story-001-a1', true),
  ('story-001', 'story-001-a2', true),
  ('story-001', 'story-001-a3', true)
on conflict (story_id, article_id) do update set
  same_event_verified = excluded.same_event_verified;

commit;

-- 5. 저장 결과 확인: story-001 한 줄, article_count=3, publisher_count=3, ready.
-- SQL Editor는 높은 권한으로 실행되므로 공개 조건도 명시적으로 확인합니다.
select
  s.id as news_id,
  s.title,
  s.summary_status,
  count(a.id) as article_count,
  count(distinct a.publisher_id) as publisher_count
from public.stories s
left join public.story_articles sa
  on sa.story_id = s.id and sa.same_event_verified = true
left join public.articles a
  on a.id = sa.article_id and a.publish_allowed = true
where s.id = 'story-001'
  and s.is_demo = true
  and s.published_at <= now()
  and s.retracted_at is null
group by s.id, s.title, s.summary_status;
