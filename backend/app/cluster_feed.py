"""Read the namespace's completed candidate head; raw article bodies stay private."""
from hashlib import sha256
import os

from sqlalchemy import text

from .article_images.metadata import safe_image_url
from .cluster_preview import VISUALS,_date
from .cluster_store.repository import _engine
from .models import Story
from .news_topics import display_category, VERSION as TOPIC_VERSION
from .rss_preview import plain_text
from .scheduled_news.repository import namespace as check_namespace,_schema


class ClusterFeedError(ValueError):pass


def story_identity(namespace, group_id):
    return 'db-cluster-' + sha256((namespace+'\0'+group_id).encode()).hexdigest()[:24]


def legacy_story_identity(group_id):
    return 'local-cluster-' + sha256(group_id.encode()).hexdigest()[:24]


def _require(value):
    if not value:raise ClusterFeedError('Incomplete or inconsistent completed DB candidate batch')


def project_batch(namespace,batch_id,articles,groups,members):
    check_namespace(namespace)
    _require(0<len(articles)<=2000 and 0<len(groups)<=len(articles))
    by_id={a['article_id']:a for a in articles}
    _require(len(by_id)==len(articles))
    linked={};seen=set()
    for member in members:
        identity=member['article_id']
        _require(identity in by_id and identity not in seen)
        linked.setdefault(member['group_id'],[]).append(identity);seen.add(identity)
    _require(seen==set(by_id) and len(linked)==len(groups))
    group_ids=set();stories=[]
    for group in groups:
        identity=group['group_id'];primary=group['representative_article_id']
        _require(identity not in group_ids and identity in linked)
        group_ids.add(identity)
        ids=linked[identity]
        _require(primary in ids and group['same_event_verified'] is False)
        if 'article_count' in group:_require(group['article_count']==len(ids))
        sources=[];dates=[]
        for key in [primary,*sorted(a for a in ids if a!=primary)]:
            article=by_id[key];rights=article['rights']
            _require(rights.get('collect')=='allowed' and rights.get('store')=='allowed')
            date=_date(article['published_at']);dates.append(date)
            image=article.get('image_url') if rights.get('display_image')=='allowed' else None
            name=plain_text(article['publisher']);_require(bool(name))
            sources.append(dict(id=key,publisher_id='cluster-publisher-'+sha256(article['publisher'].encode()).hexdigest()[:24],
                publisher_name=name,title=article['title'],url=article['url'],published_at=date,
                framing=('대표기사' if key==primary else '군집 관련 기사')+' · 동일 사건 검토 전',
                is_demo=article['is_demo'],image_url=safe_image_url(image)))
        category=group['category'];_require(category in VISUALS)
        category=display_category(category,by_id[primary]['title'])
        unknowns=['자동 군집 후보입니다. 관련 기사들이 같은 사건을 다루는지 확인해주세요.',
                  'AI 요약을 생성하지 않았습니다. 대표기사와 언론사별 원문 링크를 제공합니다.']
        flagged=group.get('quality_review_required',group.get('review',{}).get('quality_review_required',False))
        if flagged:unknowns.append('검토 필요: 군집 품질 점검 대상으로 표시된 기사입니다. 관련 원문을 확인해주세요.')
        stories.append(Story.model_validate(dict(
            id=story_identity(namespace, identity),
            title=by_id[primary]['title'],category=category,
            dek=f'관련 기사 {len(ids)}개 · 대표기사와 출처를 확인하세요. AI 요약은 아직 생성하지 않았습니다.',
            updated_at=max(dates),keywords=[],visual=VISUALS[category],
            coverage=dict(publisher_count=len({a['publisher_id'] for a in sources}),article_count=len(ids),
                          perspective_count=0,label_status='unverified'),
            summary=dict(status='pending',bullets=[],unknowns=unknowns),perspectives=[],
            articles=sources,public_interest=0,is_demo=all(a['is_demo'] for a in sources))))
    notes=[f'DB에 저장된 기사 {len(articles)}개 → 대표기사 {len(stories)}개를 표시합니다.',
           '로컬 테스트용 군집 후보입니다. 동일 사건 여부·정확도와 언론사 이용 허가는 확인 전입니다.',
           '제목·출처·관련 기사 수를 제공합니다. 원문 전문과 AI 요약은 화면에 제공하지 않습니다.',
           '사진은 테스트 입력의 표시 허용 설정을 따릅니다. 외부 배포 전에 출처별 허용 범위를 확인해야 합니다.']
    return stories,notes


def load_cluster_feed(*,namespace=None,engine=None,include_aliases=False):
    namespace=check_namespace(namespace or os.getenv('PRISM_CLUSTER_NAMESPACE','scheduled-local-test'))
    try:
        with _engine(engine).connect() as c,c.begin():
            c.execute(text('SET TRANSACTION READ ONLY'))
            _schema(c)
            head=c.execute(text('''SELECT b.batch_id,b.article_count,b.group_count,h.analyzed_at,h.input_sha256
                FROM private.prism_cluster_heads h JOIN private.prism_cluster_batches b ON b.batch_id=h.batch_id
                WHERE h.namespace=:ns AND b.namespace=:ns'''),dict(ns=namespace)).mappings().first()
            if head is None:
                empty = ([], 'cluster-db-empty-'+sha256(namespace.encode()).hexdigest()[:16], [
                    'DB 군집 결과를 기다리고 있습니다. 수집·분석이 성공하면 대표기사가 표시됩니다.',
                    '로컬 테스트용 군집 후보이며 AI 요약은 생성하지 않습니다.'])
                return (*empty, {}) if include_aliases else empty
            batch=head['batch_id']
            # record contains metadata only: SELECT never retrieves raw_text.
            article_rows=c.execute(text('SELECT article_id,record,image_url,rights FROM private.prism_cluster_articles WHERE batch_id=:batch LIMIT 2001'),dict(batch=batch)).mappings().all()
            groups=c.execute(text('SELECT group_id,representative_article_id,category,article_count,same_event_verified,review FROM private.prism_cluster_groups WHERE batch_id=:batch LIMIT 2001'),dict(batch=batch)).mappings().all()
            members=c.execute(text('SELECT group_id,article_id FROM private.prism_cluster_members WHERE batch_id=:batch LIMIT 2001'),dict(batch=batch)).mappings().all()
            _require(len(article_rows)==head['article_count'] and len(groups)==head['group_count'])
            articles=[]
            for row in article_rows:
                record=dict(row['record'])
                _require(record['article_id']==row['article_id'] and record['rights']==row['rights'])
                articles.append({**record,'image_url':row['image_url']})
        stories,notes=project_batch(namespace,batch,articles,groups,members)
        from .services.editorial import overlay
        stories,editorial_version=overlay(stories,namespace,batch,engine=engine,source_rows=article_rows,members=members)
        ready_count=sum(s.summary.status=='ready' for s in stories)
        if ready_count:
            notes[2]=f'승인된 AI 요약 {ready_count}개와 기사별 출처를 제공합니다. 나머지는 대표기사로 표시합니다.'
        notes.append('마지막 분석 완료: '+head['analyzed_at'].isoformat())
        # Head changes can activate an old immutable batch again. Include input
        # identity, not its original insertion timestamp, in cursor invalidation.
        result = (stories,'cluster-db-'+sha256((namespace+'\0'+batch+'\0'+head['input_sha256']+'\0'+editorial_version+'\0'+TOPIC_VERSION).encode()).hexdigest()[:20],notes)
        aliases = {legacy_story_identity(g['group_id']):story_identity(namespace,g['group_id']) for g in groups}
        return (*result, aliases) if include_aliases else result
    except ClusterFeedError:raise
    except Exception:
        raise ClusterFeedError('Completed DB cluster snapshot is unavailable') from None
