"""Read-only local representative-article report. A body preview is not a summary."""

from html import escape
from urllib.parse import urlsplit


def _link(article):
    title, url = article['title'], article.get('url', '')
    try:
        valid = isinstance(url, str) and urlsplit(url).scheme in {'https', 'http'} and bool(urlsplit(url).netloc)
    except ValueError:
        valid = False
    if not valid:
        return escape(title)
    return f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(title)}</a>'


def render_report(result):
    cards = []
    for group in result['groups']:
        article = group['representative']
        metadata = ' · '.join(str(article.get(key) or '미상') for key in ('publisher', 'published_at', 'category'))
        related = ''.join(f'<li>{_link(other)} <small>{escape(other.get("publisher", ""))}</small></li>'
                          for other in group['related_articles'])
        preview = article['body'][:240]
        if len(article['body']) > 240:
            preview += '…'
        score = group['representative_mean_cosine']
        score_text = f'군집 내 평균 유사도 {score:.4f}' if score is not None else '단독 기사'
        quality_notice = ('<p class="notice">검토 필요: 동일한 본문에 서로 다른 제목이 붙어 있습니다. '
                          '공통 본문만으로 같은 사건을 확정할 수 없습니다.</p>') if group.get('quality_review_required') else ''
        cards.append(f'''<section class="card"><div class="tag">묶음 내 {group['article_count']}기사 · {group['publisher_count']}언론사</div>
{quality_notice}<h2>{_link(article)}</h2><p class="meta">{escape(metadata)}</p><h3>본문 미리보기</h3><p>{escape(preview)}</p>
<p class="meta">{score_text} · 대표성 기준이며 기사 품질 점수는 아닙니다.</p>
<details><summary>대표기사 본문 펼치기</summary><p class="body">{escape(article['body'])}</p></details>
<details><summary>나머지 관련 기사 {len(group['related_articles'])}건</summary><ul>{related}</ul></details></section>''')
    notice = ('각 군집의 대표기사 1개를 표시합니다. 제목과 본문을 E5로 수치화하고 K-means 및 제목·시간·유사도 조건으로 묶었습니다. '
              '대표기사는 군집 내 평균 의미 유사도가 가장 높은 기존 기사입니다. 같은 사건 여부는 확정되지 않았습니다.')
    if result.get('profile') in {'multiview', 'multiview-dev', 'multiview-group', 'multiview-anchor'}:
        detail = result['multiview']
        notice += (f' 선택형 추가 검증: 전체 본문·도입부 이중 비교. 기존 v2에 더한 연결 {detail["added_pair_count"]}쌍, '
                   f'추가 검증과 불일치하는 기존 연결 {detail["baseline_view_disagreement_count"]}쌍. '
                   '연결 수 변화는 정확도 향상률이 아니며 기존 v2 묶음은 유지합니다.')
        if detail.get('development_tuned'):
            notice += ' 이 옵션은 이미 본 개발 기사로 조정한 실험 설정이며 독립 테스트 성능은 미검증입니다.'
        if detail.get('neighbor_scope') == 'seed_group':
            notice += ' 군집 단위 후보 검색: 모든 교차 기사 쌍이 조건을 통과한 군집을 가장 낮은 도입부 유사도로 정렬합니다.'
        if result.get('profile') == 'multiview-anchor':
            quality = result['quality_audit']
            notice += (f' 한국은행 결정의 원문 근거로 보완한 교차 쌍 {quality["grouped_anchor_pair_count"]}개. '
                       '발표 주체·당일 날짜·결정 내용과 기존의 강한 연결을 함께 확인한 개발용 규칙입니다. '
                       f'동일 본문·다른 제목 검토 후보 {quality["shared_summary_cluster_count"]}묶음. '
                       '이 표시는 사건 오류 정답이나 검증된 정확도를 뜻하지 않습니다.')
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>로컬 뉴스 대표기사</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f2f6fb;color:#1b3048;font-family:Malgun Gothic,sans-serif;line-height:1.7}}
main{{max-width:1080px;margin:auto;padding:28px 20px 50px}}h1{{margin-bottom:8px}}h2{{font-size:21px;margin:8px 0}}h3{{font-size:14px;margin-bottom:0}}a{{color:#155b9b;text-decoration:none}}a:hover{{text-decoration:underline}}
.notice{{padding:16px;background:#fff1ce;border-left:4px solid #c78a19}}.card{{background:white;margin:18px 0;padding:22px;border:1px solid #dce5ef;border-radius:12px}}
.meta,small{{font-size:13px;color:#60738b;overflow-wrap:anywhere}}.tag{{font-weight:bold;color:#216399;font-size:13px}}details{{margin-top:12px}}summary{{cursor:pointer}}.body{{white-space:pre-wrap;overflow-wrap:anywhere}}</style></head>
<body><main><h1>로컬 뉴스 대표기사</h1><p>본문 포함 기사 {result['article_count']}건 → 대표기사 {result['group_count']}건 · 제외 {result['skipped_count']}건</p>
<p class="notice">{notice}</p>{''.join(cards) or '<p>사용할 수 있는 기사 본문이 없습니다. input.json과 skipped.json에서 수집 상태를 확인해 주세요.</p>'}
<p class="meta">본문 미리보기는 원문의 앞부분입니다. 자동 요약을 생성하지 않았습니다. 이 파일은 로컬 검토용이며 자동 게시하지 않습니다.</p></main></body></html>'''
