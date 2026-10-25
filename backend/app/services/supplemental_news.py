"""Append explicitly collected articles as single-article candidates.

Existing groups and article text stay unchanged. This path does not claim to run
E5 clustering; the scheduled worker can regroup these candidates later.
"""
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
from sqlalchemy import text
from ..cluster_store.bundle import canonical,validate_bundle,VERSION
from ..cluster_store.repository import _engine,store_bundle
from ..scheduled_news.repository import Repository,validate_rows
from .editorial import fingerprint,valid_output


def snapshot(namespace,*,engine=None):
    with _engine(engine).connect() as c,c.begin():
        c.execute(text('SET TRANSACTION READ ONLY'))
        head=c.execute(text('SELECT batch_id FROM private.prism_cluster_heads WHERE namespace=:ns'),{'ns':namespace}).scalar_one()
        meta=c.execute(text('SELECT source_hashes FROM private.prism_cluster_batches WHERE batch_id=:b'),{'b':head}).scalar_one()
        articles=[dict(r['record'])|{'body':r['raw_text']} for r in c.execute(text('SELECT record,raw_text FROM private.prism_cluster_articles WHERE batch_id=:b ORDER BY article_id'),{'b':head}).mappings()]
        members={}
        for r in c.execute(text('SELECT group_id,article_id FROM private.prism_cluster_members WHERE batch_id=:b'),{'b':head}).mappings():members.setdefault(r['group_id'],[]).append(r['article_id'])
        groups=[{'group_id':r['group_id'],'category':r['category'],'representative_article_id':r['representative_article_id'],
                 'article_ids':sorted(members[r['group_id']]),'same_event_verified':False,
                 'quality_review_required':r['review']['quality_review_required'],'quality_review_reasons':r['review']['reasons']}
                for r in c.execute(text('SELECT * FROM private.prism_cluster_groups WHERE batch_id=:b ORDER BY group_id'),{'b':head}).mappings()]
    return head,{'namespace':namespace,'automatic_publication':False,'accuracy_measured':False,'requires_human_review':True,
                 'sources':meta,'articles':articles,'groups':groups}


def prepare(payload,rows):
    result=deepcopy(payload);known={a['article_id']:a for a in result['articles']};urls={a['url'] for a in known.values()}
    added=[]
    for row in validate_rows(rows):
        if row['article_id'] in known:
            if known[row['article_id']]['content_hash']!=row['content_hash']:raise ValueError('Existing article changed; use the analysis pipeline')
            continue
        if row['url'] in urls:raise ValueError('Article URL already has a different ID')
        article={key:row[key] for key in ('article_id','title','body','url','publisher','source_id','category','published_at','body_kind','source_notice','content_hash','body_sha256','image_url','rights','is_demo')}
        article['original_category']=row['category'];result['articles'].append(article);urls.add(row['url']);added.append(row['article_id'])
        result['groups'].append({'group_id':'intake-singleton-'+sha256(row['article_id'].encode()).hexdigest()[:24],
          'category':row['category'],'representative_article_id':row['article_id'],'article_ids':[row['article_id']],
          'same_event_verified':False,'quality_review_required':True,'quality_review_reasons':['single_article_intake_not_clustered']})
    result['articles'].sort(key=lambda r:r['article_id']);result['groups'].sort(key=lambda r:r['group_id'])
    if added:
        result['sources']={key:sha256(canonical(value).encode()).hexdigest() for key,value in {
          'articles':result['articles'],'representatives':result['groups'],'input':{'previous':payload['sources'],'added':added},
          'images':[(a['article_id'],a['image_url']) for a in result['articles']]}.items()}
    digest=sha256(canonical(result).encode()).hexdigest()
    return validate_bundle({'schema_version':VERSION,'batch_id':'prism-batch-'+digest,'payload_sha256':digest,'payload':result}),added


def article_rows(payload,group):
    ids=set(group['article_ids'])
    return [{'article_id':a['article_id'],'record':{k:v for k,v in a.items() if k!='body'},
             'body_sha256':a['body_sha256'],'content_hash':a['content_hash'],'rights':a['rights']}
            for a in payload['articles'] if a['article_id'] in ids]


def append(namespace,rows,*,engine=None):
    repo=Repository(engine);db=_engine(engine)
    with repo.lock(namespace) as acquired:
        if not acquired:raise ValueError('News worker is running; retry later')
        previous,payload=snapshot(namespace,engine=db);bundle,added=prepare(payload,rows)
        if not added:return {'added':0,'preserved_groups':len(payload['groups']),'copied_reviews':0}
        store_bundle(bundle,engine=db)
        copied=0
        # 활성 포인터를 잠그고 기존 기사·멤버가 동일한 승인 결과만 보존합니다.
        # 새 정치 기사는 군집 재분석 결과가 아닌 단일 기사 후보입니다.
        with db.begin() as c:
            current=c.execute(text('SELECT batch_id FROM private.prism_cluster_heads WHERE namespace=:ns FOR UPDATE'),{'ns':namespace}).scalar_one()
            if current!=previous:raise ValueError('Active news changed while preparing the supplement')
            for group in payload['groups']:
                records=article_rows(payload,group);ids={r['article_id'] for r in records}
                old_hash=fingerprint(namespace,previous,group['group_id'],records)
                new_hash=fingerprint(namespace,bundle['batch_id'],group['group_id'],records)
                approved=c.execute(text("SELECT * FROM private.prism_editorial_summaries WHERE namespace=:ns AND batch_id=:b AND group_id=:g AND input_hash=:h AND review_status='approved'"),{'ns':namespace,'b':previous,'g':group['group_id'],'h':old_hash}).mappings().all()
                for row in approved:
                    valid_output(row['output'],ids)
                    c.execute(text("""INSERT INTO private.prism_editorial_summaries(namespace,batch_id,group_id,input_hash,model_version,prompt_version,output,review_status,reviewed_at)
                      VALUES (:ns,:b,:g,:h,:m,:p,cast(:o AS jsonb),'approved',:at) ON CONFLICT DO NOTHING"""),
                      {'ns':namespace,'b':bundle['batch_id'],'g':group['group_id'],'h':new_hash,'m':row['model_version'],'p':row['prompt_version'],'o':canonical(row['output']),'at':row['reviewed_at']})
                    copied+=1
            c.execute(text('UPDATE private.prism_cluster_heads SET batch_id=:b,input_sha256=:h,analyzed_at=:at WHERE namespace=:ns'),
                      {'b':bundle['batch_id'],'h':bundle['payload_sha256'],'at':datetime.now(timezone.utc),'ns':namespace})
        repo.ingest(namespace,rows,observed_at=datetime.now(timezone.utc))
        return {'added':len(added),'preserved_groups':len(payload['groups']),'copied_reviews':copied}
