"""Pair annotation and evaluation. Predictions never become gold labels."""
from collections import Counter
from hashlib import sha256
from itertools import combinations
import json
from sqlalchemy import text
from ..cluster_store.repository import _engine


def assessment(*,engine=None,namespace='scheduled-local-test'):
    with _engine(engine).connect() as c,c.begin():
        c.execute(text('SET TRANSACTION READ ONLY'))
        batch=c.execute(text('SELECT batch_id FROM private.prism_cluster_heads WHERE namespace=:n'),{'n':namespace}).scalar_one_or_none()
        if batch is None: raise ValueError('평가할 군집 결과가 없습니다.')
        rows=c.execute(text('''SELECT a.article_id,a.title,a.publisher_name,a.category,a.published_at,a.body_sha256,
            char_length(a.raw_text) AS body_chars,m.group_id FROM private.prism_cluster_articles a
            JOIN private.prism_cluster_members m ON m.batch_id=a.batch_id AND m.article_id=a.article_id
            WHERE a.batch_id=:b ORDER BY a.article_id'''),{'b':batch}).mappings().all()
    if len(rows)>500: raise ValueError('평가 도구의 기사 한도 500개를 초과했습니다.')
    groups=Counter(r['group_id'] for r in rows)
    fingerprint=sha256(json.dumps([(r['article_id'],r['body_sha256'],r['group_id']) for r in rows],ensure_ascii=False).encode()).hexdigest()
    pairs=[{'a':a['article_id'],'b':b['article_id'],'a_title':a['title'],'b_title':b['title'],
        'a_publisher':a['publisher_name'],'b_publisher':b['publisher_name'],
        'predicted_same_event':a['group_id']==b['group_id'],'same_event':None} for a,b in combinations(rows,2)]
    return {'schema_version':'prism-pair-review/v1','batch_id':batch,'input_hash':fingerprint,
        'article_count':len(rows),'group_count':len(groups),'singleton_groups':sum(n==1 for n in groups.values()),
        'publishers':dict(Counter(r['publisher_name'] for r in rows)),
        'categories':dict(Counter(r['category'] for r in rows)),
        'missing_body_count':sum(not r['body_chars'] for r in rows),
        'duplicate_body_count':len(rows)-len({r['body_sha256'] for r in rows}),
        'accuracy_measured':False,'pairs':pairs,
        'notice':'same_event는 사람이 같은 사건인지 판단해 true/false로 작성합니다. 예측값을 정답으로 복사하지 마세요.'}


def evaluate(template,labels):
    if not isinstance(labels,dict) or labels.get('input_hash')!=template['input_hash'] or labels.get('batch_id')!=template['batch_id']:
        raise ValueError('평가 파일과 현재 데이터 버전이 일치하지 않습니다.')
    if not isinstance(labels.get('pairs'),list): raise ValueError('pairs 목록이 필요합니다.')
    predictions={tuple(sorted((p['a'],p['b']))):p['predicted_same_event'] for p in template['pairs']}
    seen=set();counts=Counter(tp=0,fp=0,fn=0,tn=0)
    for p in labels['pairs']:
        if not isinstance(p,dict) or not isinstance(p.get('a'),str) or not isinstance(p.get('b'),str): raise ValueError('잘못된 기사 쌍입니다.')
        pair=tuple(sorted((p['a'],p['b'])))
        if pair in seen or pair not in predictions: raise ValueError('중복되었거나 알 수 없는 기사 쌍입니다.')
        seen.add(pair);gold=p.get('same_event')
        if gold is None: continue
        if type(gold) is not bool: raise ValueError('정답은 true/false/null이어야 합니다.')
        prediction=predictions[pair]
        counts['tp' if prediction and gold else 'fp' if prediction else 'fn' if gold else 'tn']+=1
    n=sum(counts.values());tp,fp,fn=counts['tp'],counts['fp'],counts['fn']
    return {**counts,'labeled_pairs':n,'total_pairs':len(predictions),'label_coverage':n/len(predictions) if predictions else 0,
        'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,
        'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
        'accuracy_measured':n>0,'complete':n==len(predictions) and n>0,
        'notice':'작성된 기사 쌍만 평가한 결과입니다. 부분 정답 결과를 전체 정확도로 일반화하지 마세요.'}
