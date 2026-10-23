"""Read saved local clusters as existing Story DTOs; no DB, model or provider."""

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit

from .models import Story
from .rss_preview import plain_text


CATEGORIES = {'정치':'politics', '경제':'economy', '사회':'society', '기술':'technology',
              'politics':'politics', 'economy':'economy', 'society':'society', 'technology':'technology'}
VISUALS = {'politics':'assembly', 'economy':'market', 'society':'city', 'technology':'research'}
ARTICLE_FIELDS = ('article_id','title','body','category','published_at','publisher','url',
                  'source_id','body_kind','source_notice','content_hash')


class ClusterPreviewError(ValueError):
    """A missing or inconsistent local run; HTTP never substitutes fixtures."""


def _require(condition):
    if not condition:
        raise ClusterPreviewError('Invalid or inconsistent local cluster artifacts')


def _text(value):
    _require(isinstance(value, str) and bool(value.strip()) and '\0' not in value)
    return value


def _count(value, expected):
    _require(type(value) is int and value == expected)


def _date(value):
    _text(value)
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _require(date.tzinfo is not None and date.utcoffset() is not None)
    return date


def _read(path):
    raw = path.read_bytes()
    _require(len(raw) <= 20_000_000)
    def reject_constant(value):
        raise ClusterPreviewError('Nonfinite value in local artifact')
    return json.loads(raw.decode('utf-8-sig'), parse_constant=reject_constant), raw


def _convert(exported, normalized, images=None):
    _require(isinstance(exported, dict) and isinstance(normalized, dict))
    _require(exported['schema_version'] == 'local-news-representatives/v1')
    _require(exported['status'] in ('completed', 'no_eligible_articles'))
    _require(exported['automatic_publication'] is False and exported['accuracy_measured'] is False)
    articles, groups = normalized['articles'], exported['groups']
    _require(isinstance(articles, list) and isinstance(groups, list) and len(articles) <= 2000)
    _count(exported['article_count'], len(articles))
    _count(exported['group_count'], len(groups))
    by_id, dates = {}, {}
    for row in articles:
        _require(isinstance(row, dict) and all(key in row for key in ARTICLE_FIELDS))
        identity = _text(row['article_id'])
        _require(identity not in by_id)
        _text(row['title'])
        _text(row['body'])
        _text(row['publisher'])
        _require(row['body_kind'] in ('provided_body','publisher_html','rss_content'))
        _require(row['content_hash'] == sha256(f"{row['title']}\n{row['body']}".strip().encode('utf-8')).hexdigest())
        dates[identity] = _date(row['published_at'])
        parsed = urlsplit(_text(row['url']))
        _require(parsed.scheme in ('http','https') and parsed.hostname and parsed.username is None and parsed.password is None)
        by_id[identity] = row
    seen, group_ids, stories = set(), set(), []
    review_groups = 0
    for group in groups:
        _require(isinstance(group, dict))
        group_id = _text(group['group_id'])
        _require(group_id not in group_ids)
        group_ids.add(group_id)
        members = group['article_ids']
        _require(isinstance(members, list) and bool(members) and all(isinstance(key, str) for key in members))
        _require(len(set(members)) == len(members) and set(members) <= set(by_id) and not (seen & set(members)))
        _count(group['article_count'], len(members))
        _count(group['publisher_count'], len({by_id[key]['publisher'] for key in members}))
        representative = group['representative']
        _require(isinstance(representative, dict) and representative['article_id'] in members)
        primary = representative['article_id']
        _require(all(representative.get(key) == by_id[primary][key] for key in ARTICLE_FIELDS))
        category = CATEGORIES[_text(group['category']).strip()]
        flagged = group.get('quality_review_required', False)
        _require(type(flagged) is bool)
        reasons = group.get('quality_review_reasons', [])
        _require(isinstance(reasons, list) and all(isinstance(reason, str) for reason in reasons))
        review_groups += int(flagged)
        source_articles = []
        for identity in [primary, *(key for key in members if key != primary)]:
            row = by_id[identity]
            name = plain_text(row['publisher'])
            _text(name)
            source_articles.append(dict(id=identity,
                publisher_id='local-publisher-' + sha256(row['publisher'].encode()).hexdigest()[:24],
                publisher_name=name, title=row['title'], url=row['url'], published_at=dates[identity],
                framing=('대표기사' if identity == primary else '군집 관련 기사') + ' · 동일 사건 검토 전',
                is_demo=False, image_url=(images or {}).get(identity)))
        text = plain_text(by_id[primary]['body'])
        excerpt = text[:240] + ('…' if len(text) > 240 else '')
        unknowns = ['자동 군집 후보입니다. 관련 기사들이 같은 사건을 다루는지 확인해주세요.',
                    'AI 요약을 생성하지 않았습니다. 아래 출처에서 원문을 확인할 수 있습니다.']
        if flagged:
            unknowns.append('검토 필요: 본문은 같고 제목이 다른 기사가 포함돼 있습니다. 기사별 원문을 확인해주세요.')
        stories.append(Story.model_validate(dict(
            id='local-cluster-' + sha256(group_id.encode()).hexdigest()[:24],
            title=by_id[primary]['title'], category=category,
            dek='대표기사 본문 발췌 · ' + (excerpt or '표시할 발췌가 없습니다. 원문을 확인해주세요.'),
            updated_at=max(dates[key] for key in members), keywords=[], visual=VISUALS[category],
            coverage=dict(publisher_count=group['publisher_count'], article_count=len(members),
                          perspective_count=0, label_status='unverified'),
            summary=dict(status='pending', bullets=[], unknowns=unknowns,
                         model_version=None, prompt_version=None),
            perspectives=[], articles=source_articles, public_interest=0, is_demo=False)))
        seen.update(members)
    _require(seen == set(by_id))
    notes = [f"저장된 본문 기사 {len(articles)}개 → 대표기사 {len(stories)}개를 표시합니다.",
             '로컬 군집분석 결과 미리보기입니다. 같은 사건 여부와 정확도는 검증되지 않았습니다.',
             '본문 앞부분을 발췌했으며 AI 요약·관점 분류·보도 품질 점수를 만들지 않았습니다.',
             '표시용 사건·출처 ID는 로컬 ID이며 DB에 저장하거나 자동 게시하지 않습니다.']
    if review_groups:
        notes.append(f'본문 재사용을 확인할 군집 후보 {review_groups}개가 있습니다.')
    return stories, notes


def load_cluster_preview(folder, image_manifest=None):
    """Return Stories, a content-bound version and notices from one saved run."""
    try:
        directory = Path(folder).resolve()
        exported, export_bytes = _read(directory/'representatives.json')
        normalized, article_bytes = _read(directory/'articles.json')
        stories, notes = _convert(exported, normalized)
        image_bytes = None
        image_input_bytes = None
        if image_manifest:
            image_bytes = b'image-metadata-unavailable'
            try:
                from .article_images import images_from_manifest
                image_bytes = Path(image_manifest).read_bytes()
                image_input_bytes = (directory/'input.json').read_bytes() if (directory/'input.json').is_file() else None
                images = images_from_manifest(image_bytes, article_bytes, export_bytes, normalized['articles'], image_input_bytes)
                stories, _ = _convert(exported, normalized, images)
                count = sum(bool(story.articles[0].image_url) for story in stories)
                notes.append(f'대표기사 이미지 {count}/{len(stories)}개를 원문 출처에서 연결했습니다. 로컬 미리보기이며 이미지 이용 허가를 확인한 결과는 아닙니다.')
            except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
                notes.append('이미지 정보를 확인하지 못했습니다. 기사 내용은 유지하고 기본 이미지를 표시합니다.')
        version_bytes = export_bytes + b'\0' + article_bytes
        if image_bytes is not None:
            version_bytes += b'\0images\0' + image_bytes + b'\0source-input\0' + (image_input_bytes or b'')
        version = 'cluster-local-' + sha256(version_bytes).hexdigest()[:20]
        return stories, version, notes
    except ClusterPreviewError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ClusterPreviewError('Local cluster artifacts are missing or inconsistent') from None
