"""Exact cosine retrieval over permitted chunks in the selected active news only."""
from hashlib import sha256
import os
import numpy as np
from sqlalchemy import bindparam,text
from ..cluster_store.repository import _engine
from ..services.cluster_context import chat_cluster_bodies
from .embeddings import encoder as default_encoder


def chunk_id(batch,article,body_hash,start,end,model):
    return sha256(f'{batch}\0{article}\0{body_hash}\0{start}\0{end}\0{model}'.encode()).hexdigest()


def vector(value):
    v=np.asarray(value,dtype=np.float32)
    if v.shape not in {(384,),(1024,)} or not np.isfinite(v).all() or not .99<=float(np.linalg.norm(v))<=1.01: raise ValueError('잘못된 검색 벡터입니다.')
    return v


def retrieve(story,question,*,engine=None,encoder=None,top_k=6,budget=9000):
    if not 1<=top_k<=12 or not 500<=budget<=16000: raise ValueError('검색 범위 설정을 확인해주세요.')
    documents=chat_cluster_bodies(story,engine=engine,per_article_limit=200000,total_limit=500000,with_provenance=True)
    enc=encoder or default_encoder();db=_engine(engine)
    chunks=[]
    for document in documents:
        params={'b':document['batch_id'],'a':document['article_id'],'h':document['body_sha256'],'m':enc.model_id}
        spans=enc.chunks(document['text'])
        if len(spans)>2000: raise ValueError('기사 청크 수가 검색 한도를 초과했습니다.')
        expected={chunk_id(params['b'],params['a'],params['h'],s,e,params['m']):(s,e) for s,e in spans}
        with db.connect() as c:
            rows=c.execute(text('''SELECT chunk_id,start_offset,end_offset,embedding FROM private.prism_rag_chunks
                WHERE batch_id=:b AND article_id=:a AND body_sha256=:h AND model_id=:m'''),params).mappings().all()
        existing={r['chunk_id']:r for r in rows}
        missing=[(identity,*span) for identity,span in expected.items() if identity not in existing]
        if missing:
            embeddings=enc.encode([document['text'][s:e] for _,s,e in missing])
            if len(embeddings)!=len(missing): raise ValueError('청크와 벡터 개수가 다릅니다.')
            with db.begin() as c:
                for (identity,start,end),embedding in zip(missing,embeddings):
                    v=vector(embedding)
                    c.execute(text('''INSERT INTO private.prism_rag_chunks(batch_id,article_id,model_id,body_sha256,chunk_id,start_offset,end_offset,embedding)
                        VALUES (:b,:a,:m,:h,:id,:s,:e,:v) ON CONFLICT DO NOTHING'''),{**params,'id':identity,'s':start,'e':end,'v':v.tolist()})
                    existing[identity]={'start_offset':start,'end_offset':end,'embedding':v}
        for identity,(start,end) in expected.items():
            row=existing[identity]
            if (row['start_offset'],row['end_offset'])!=(start,end): raise ValueError('저장된 검색 구간이 원문과 다릅니다.')
            chunks.append({'chunk_id':identity,'article_id':document['article_id'],'start':start,'end':end,'text':document['text'][start:end],
                'is_excerpt':start>0 or end<document['source_length'],'vector':vector(row['embedding'])})
    if not chunks: raise ValueError('검색 가능한 본문이 없습니다.')
    q=vector(enc.encode([question],query=True)[0])
    for c in chunks:
        if q.shape!=c['vector'].shape:raise ValueError('질문과 기사 임베딩 모델 차원이 다릅니다.')
        c['score']=float(np.dot(q,c['vector']))
    ranked=sorted(chunks,key=lambda c:(-c['score'],c['article_id'],c['start']))
    selected=[];remaining=budget
    # Pure summary requests receive a broader selection across members.
    broad=any(word in question for word in ('요약','전체','핵심','정리','쉽게'))
    if broad:
        first={}
        for c in ranked:first.setdefault(c['article_id'],c)
        candidates=list(first.values())+ranked
    else:candidates=ranked
    for c in candidates:
        if len(selected)>=top_k or remaining<=0: break
        if any(c['article_id']==s['article_id'] and min(c['end'],s['end'])>max(c['start'],s['start']) for s in selected): continue
        content=c['text'][:remaining];remaining-=len(content)
        selected.append({k:c[k] for k in ('chunk_id','article_id','start','end') }|{'text':content,'is_excerpt':c['is_excerpt'] or len(content)<len(c['text'])})
    # A completed batch switch must not silently bind old chunks to a new story.
    with db.connect() as c:
        head=c.execute(text('SELECT batch_id FROM private.prism_cluster_heads WHERE namespace=:n'),{'n':documents[0]['namespace']}).scalar_one_or_none()
        if head!=documents[0]['batch_id']: raise ValueError('뉴스가 갱신되었습니다. 새로고침해주세요.')
    return selected
