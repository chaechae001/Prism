# RSS 4개사·8개 피드 스키마 점검 및 백엔드 인계

점검일: 2026-10-21. **현재 저장소의 SQL/입력 모델은 일부 기본 항목만 반영하고 있습니다. RSS별 차이를 충분히 반영한 완성 스키마는 아닙니다.**

이 문서는 프론트 담당이 백엔드 담당에게 전달하는 검토 결과입니다. 이번 작업에서 `backend/`, `database/`, `contracts/`는 수정하거나 DB에 적용하지 않았습니다. 팀원이 다른 PC/브랜치에서 수정 중인 최신 DB는 직접 확인하지 못했으므로, 그 작업과 아래 내용을 대조해야 합니다.

## 1. 실제 응답을 확인한 범위

8개 공식 RSS URL에 각각 GET 요청을 보내 XML 구조와 처음 3개 item의 필드 이름을 확인했습니다. 기사 제목·본문·이미지·저자 원문은 파일에 보관하지 않았고, LLM에 보내지 않았습니다. 관측한 필드와 개수만 `rss-field-observations.json`에 기록했습니다. 한 시점의 샘플이므로 이후 필드·건수는 바뀔 수 있습니다.

| 소스 | 경제/정치 응답 | 처음 3개 item의 필드 관측 | 스키마에서 주의할 점 |
|---|---|---|---|
| 한국경제 | 200, 각 50 item | title, link, author, pubDate | description·guid·본문·이미지 필드를 관측하지 못함. 본문/요약 필수 가정 불가 |
| 매일경제 | 200, 각 50 item | no, title, link, category, author, pubDate, description, media:content | no는 소스 내부 ID. description은 본문과 분리. media 속성과 이미지 사용 허용은 별개 |
| SBS | 200, 각 29 item | title, link, guid, pubDate, author, description, category, enclosure, content:encoded, media:thumbnail, media:content | HTML 콘텐츠·미디어 별도 처리. content:encoded가 있다는 사실만으로 기사 전문·이용 허용을 확정하지 않음 |
| 경향신문 | 200, 각 50 item | dc:creator, title, link, guid, description, dc:date, category | 샘플에 pubDate가 없고 dc:date 사용. namespace를 인식해야 함 |

공식 피드 안내: [한국경제](https://www.hankyung.com/feed), [매일경제](https://www.mk.co.kr/rss), [SBS](https://news.sbs.co.kr/news/rss.do?cooper=SBSNEWS&plink=SITEMAP), [경향신문](https://www.khan.co.kr/help/help_rss.html).

SBS content:encoded는 첫 경제 item 2,751자, 첫 정치 item 3,149자로 관측했지만, HTML·영상·서식이 포함될 수 있으므로 그 길이를 기사 본문 길이나 전문 제공 보장으로 해석하지 않습니다. 나머지 소스의 description도 ‘AI 요약’이나 ‘전문’으로 자동 표기하지 않습니다.

## 2. 현재 코드와의 차이

| 현재 위치 | 반영된 부분 | 부족하거나 확인할 부분 |
|---|---|---|
| public.publishers | 언론사 ID·이름·소유 그룹 | 언론사마다 여러 피드를 등록하는 feed/source 테이블 없음 |
| public.articles | 제목·언론사·URL·발행일 | source_item_id/guid, 원본 카테고리, 저자, RSS description, 미디어/기여자 메타데이터 없음 |
| private.raw_articles | 본문·해시·수집 시각·권한·배치 | raw_text NOT NULL 가정. 텍스트 없는 RSS를 적재하는 단계를 별도로 둘 필요 |
| ArticleInput | category, canonical_url, publisher/group, 날짜·권한 | text 최소 1자 필수. 한국경제 관측 응답만으로는 이 모델을 충족할 수 없음 |
| Story API | 사건·요약·관점·출처 연결 | 표시용 모델로는 계속 사용 가능. RSS 원본 필드를 모두 공개 API에 노출할 필요 없음 |
| 날짜 필터 API | 현재 없음 | 새 UI는 로드된 사건의 updated_at을 KST로 필터링. 서버 전체 기간 검색은 미구현 |

`ArticleInput`을 RSS 수신 모델로 바로 사용하지 않는 것을 권합니다. **RSS 수신 → 정규화 → 권한·본문 충분성 확인 → 분석 입력**을 구분하세요. 본문이 없다고 자동으로 원문 웹페이지를 크롤링하는 처리를 넣지 않습니다.

## 3. 백엔드 담당에게 요청할 데이터 구조

다음은 **추가 제안**이며 현재 SQL/API에 적용된 내용이 아닙니다. 이름·타입은 팀원이 실제 스키마와 맞춰 결정합니다.

| 테이블/영역 제안 | 주요 필드 | 이유 |
|---|---|---|
| sources/feeds | id, publisher_id, feed_url, default_category, format, enabled | 언론사 1개 ↔ 경제/정치 등 여러 피드 |
| 비공개 RSS intake | feed_id, source_item_id nullable, original_url, canonical_url, title, author nullable, source_category nullable | 누락과 서로 다른 ID 체계를 흡수 |
| 비공개 콘텐츠 | rss_description nullable, content_html nullable, body_text nullable, body_status, content_origin | 발행사 설명·본문·AI 생성 요약을 혼동하지 않음 |
| 날짜 | source_published_raw nullable, published_at nullable, collected_at, parse_status | dc:date/pubDate 정규화 실패를 수집 시각으로 조용히 대체하지 않음 |
| 미디어 | media_url nullable, mime_type nullable, origin, rights_status | 이미지 없는 카드 지원, 허용 여부 확인 전 실제 사진 재표시 보류 |
| 권한 정책 | collect/store/summarize/publish_summary/display_image 별 상태, policy_url, checked_at, evidence | 피드 접근 가능과 앱 재사용 허용을 구분 |
| 수집 상태 | last_attempt_at, last_success_at, http_status, etag nullable, last_modified nullable, error_code | 장애·중복·조건부 요청·운영 확인 |
| 범위 | publisher_country, article_language, event_geography nullable/unknown | 국내 언론사 발행과 국내 사건을 구분 |

권한을 확인하지 않은 소스는 이번 후보 파일에서 `collect_enabled:false`와 모든 이용 단계 `unknown`으로 기록했습니다. 이는 발행사의 법적 허용/금지 상태를 판정한 값이 아니라 **이 프로젝트에서 아직 확인하지 못했다는 상태**입니다.

### ID·날짜·분류 변환 규칙

1. source_item_id는 guid → 소스 고유 no → 정규화 URL 기반 안정 ID 순으로 결정하되 소스별 namespace를 붙입니다. 매 수집마다 새 UUID를 만들지 않습니다.
2. pubDate와 dc:date를 모두 읽어 timezone이 있는 시각으로 정규화합니다. 원본 문자열과 파싱 상태를 별도로 보존합니다. 파싱 실패 항목은 검토 대기 처리합니다.
3. RSS category가 없으면 feed 기본 카테고리를 이용하고, 원본 분류와 우리 서비스의 네 가지 분류를 별도로 보존합니다. 경제 피드라는 이유만으로 국내 사건으로 판단하지 않습니다.
4. description은 nullable, body_text도 RSS intake 단계에서는 nullable입니다. 본문 누락을 허위 텍스트나 빈 문자열로 채워 분석 모델을 통과시키지 않습니다.
5. 같은 기사가 두 피드에 나타나도 기사 중복과 유입 경로 이력을 모두 다룰 수 있도록 article↔feed 관계를 고려합니다.
6. media:content / media:thumbnail / enclosure의 URL은 XML 속성에 들어갈 수 있습니다. 태그의 text만 읽는 파서로는 놓칠 수 있습니다.
7. HTML은 프론트에서 그대로 삽입하지 않습니다. 허용된 처리 경로에서 정제하고 표시용 텍스트로 변환합니다.

## 4. 참고용 RSS 정규화 JSON

아래는 신규 수신 모델을 논의하기 위한 **가상 예시**입니다. 현재 ArticleInput/공개 API에 그대로 POST하면 안 됩니다.

```json
{
  "feed_id":"hankyung-economy",
  "publisher_id":"hankyung",
  "source_item_id":null,
  "original_url":"https://example.com/fictional-rss-item",
  "canonical_url":"https://example.com/fictional-rss-item",
  "title":"가상 RSS 항목",
  "author":null,
  "source_category":null,
  "normalized_category":"economy",
  "rss_description":null,
  "content_html":null,
  "body_text":null,
  "body_status":"not_provided",
  "source_published_raw":"Wed, 21 Oct 2026 09:00:00 +0900",
  "published_at":"2026-10-21T09:00:00+09:00",
  "collected_at":"2026-10-21T09:10:00+09:00",
  "media":[],
  "license_status":"unknown",
  "parse_status":"parsed"
}
```

## 5. 이용 조건 확인 결과와 미확인 사항

- 한국경제 운영정책은 사전 승낙 없는 복사·복제·변경·타인 제공에 제한을 명시합니다. [공식 운영정책](https://www.hankyung.com/help/policy)
- 매일경제 FAQ는 허락 없는 뉴스 콘텐츠 자동 수집·저장·분석·게시를 제한하는 안내와 출처 표시만으로 허락을 대신할 수 없다는 안내를 제공합니다. [공식 저작권 FAQ](https://www.mk.co.kr/mypage/service/faq/copyright)
- 경향신문 RSS 안내는 개인 구독 목적과 다수 공유·영리 이용 시 사전 허락을 안내합니다. [공식 RSS 안내](https://www.khan.co.kr/help/help_rss.html)
- SBS는 제공하신 표에 개인 비상업 이용 조건이 기재되어 있습니다. 이번에 읽은 공식 페이지 텍스트에서는 해당 세부 문구를 독립적으로 재확인하지 못했습니다. 상업 이용·AI 처리·다중 사용자 앱 재표시 권한은 미확인 상태로 유지합니다. [공식 RSS 안내](https://news.sbs.co.kr/news/rss.do?cooper=SBSNEWS&plink=SITEMAP)

위 내용은 기술 설계를 위한 확인 상태 기록입니다. 이 작업은 실제 뉴스의 AI 처리·공개 앱 게시·언론사 이미지 재사용을 승인하지 않습니다. 현재 UI에는 기존 가상 뉴스와 직접 작성한 SVG만 사용합니다.

## 6. 팀원에게 바로 전달할 요청

> UI는 기존 Story 응답 형식을 유지하고 있어. DB/API 작업을 중단할 필요는 없어. 다만 실제 8개 RSS를 확인하니 한국경제는 description이 없고, 경향은 dc:date를 사용하며, SBS에는 별도 콘텐츠/미디어가 있어. RSS 수신 단계의 description/body/author/media를 선택값으로 두고 feed_id·source_item_id·원본 날짜·파싱 상태를 보존하는 구조를 검토해줘. 우선 가상 사건 1개+기사 3개 API 연결을 끝내고, 그다음 이 문서와 현재 스키마를 대조해 보완 목록을 알려줘. 공개 API 필드를 바꿔야 할 때는 변경 전 예시를 공유해줘. 실제 수집/AI 처리/게시 권한은 별도 확인이 필요해.

## 7. 다음 계약 변경 후보 — 아직 미구현

- 서버 기간 조회: updated_from / updated_to, 날짜 기준(updated/published), timezone, 커서 조건과의 결합. 현재 쿼리에 임의 추가하지 않았습니다.
- 사건 썸네일: nullable image_url, alt, image_source, rights_status. 허용·검토가 끝난 이미지에만 적용. 현재는 Story.visual로 기존 SVG 표시.
- 공개 API의 published_at 필수 규칙: intake에서 날짜 미확인 항목을 처리하는 정책을 먼저 결정한 뒤, 표시 대상만 검증된 날짜를 갖도록 유지할 수 있습니다.
