"""Content-free LLM records. Opik export is separately opt-in and redacted."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime,timezone
from hashlib import sha256
import json
import logging
import os
from time import perf_counter
from uuid import uuid4
from decimal import Decimal,InvalidOperation
from sqlalchemy import text
from ..cluster_store.repository import _engine

current=ContextVar('prism_llm_usage',default=None)


def usage(input_tokens,output_tokens):
    value=current.get()
    if value is not None:
        for name,n in [('input_tokens',input_tokens),('output_tokens',output_tokens)]:
            if type(n) is int and 0<=n<=10000000:value[name]=n


def estimate(record):
    if record['provider']=='ollama': return None  # Hardware/energy cost is not zero.
    try:
        rates=[Decimal(os.environ[k]) for k in ('PRISM_INPUT_USD_PER_MILLION','PRISM_OUTPUT_USD_PER_MILLION')]
        if any(not r.is_finite() or r<0 for r in rates) or record['input_tokens'] is None or record['output_tokens'] is None:return None
        return (record['input_tokens']*rates[0]+record['output_tokens']*rates[1])/1000000
    except (KeyError,InvalidOperation):return None


def save(record,*,engine=None):
    with _engine(engine).begin() as c:
        c.execute(text('''INSERT INTO private.prism_llm_runs(id,task,provider,model,prompt_version,input_hash,status,error_type,elapsed_ms,input_tokens,output_tokens,estimated_cost_usd,created_at)
            VALUES (:id,:task,:provider,:model,:prompt_version,:input_hash,:status,:error_type,:elapsed_ms,:input_tokens,:output_tokens,:estimated_cost_usd,:created_at)'''),record)


@asynccontextmanager
async def trace(task,payload,provider,model,prompt_version):
    enabled=os.getenv('PRISM_LLM_METRICS_ENABLED')=='1'
    if not enabled:
        yield;return
    start=perf_counter()
    record={'id':str(uuid4()),'task':task,'provider':provider,'model':model,'prompt_version':prompt_version,
        'input_hash':sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
        'created_at':datetime.now(timezone.utc),'status':'ok','error_type':None,'input_tokens':None,'output_tokens':None}
    token=current.set(record)
    try: yield
    except BaseException as exc:
        record.update(status='error',error_type=type(exc).__name__[:100]);raise
    finally:
        current.reset(token);record['elapsed_ms']=max(0,int((perf_counter()-start)*1000));record['estimated_cost_usd']=estimate(record)
        try:
            await asyncio.to_thread(save,record)
            if os.getenv('PRISM_OPIK_ENABLED')=='1':
                from .opik_export import export
                await asyncio.to_thread(export,record)
        except Exception as exc:
            logging.getLogger('prism.ai').warning('AI 관측 기록 저장 실패: %s',type(exc).__name__)


def report(*,engine=None):
    with _engine(engine).connect() as c,c.begin():
        c.execute(text('SET TRANSACTION READ ONLY'))
        summary=dict(c.execute(text('''SELECT count(*) AS calls,count(*) FILTER(WHERE status='error') AS errors,
            round(avg(elapsed_ms)) AS average_ms,sum(input_tokens) AS input_tokens,sum(output_tokens) AS output_tokens,
            sum(estimated_cost_usd) AS estimated_cost_usd,count(*) FILTER(WHERE estimated_cost_usd IS NOT NULL) AS cost_known_calls
            FROM private.prism_llm_runs WHERE created_at>now()-interval '24 hours' ''')).mappings().one())
        rows=c.execute(text('SELECT task,provider,model,prompt_version,status,error_type,elapsed_ms,input_tokens,output_tokens,estimated_cost_usd,created_at FROM private.prism_llm_runs ORDER BY created_at DESC LIMIT 30')).mappings().all()
    return {'last_24_hours':summary,'recent':[dict(r) for r in rows],'notice':'질문·기사 본문·답변·사용자 식별정보는 저장하지 않습니다. 비용은 설정한 단가에 따른 추정치이며 미설정은 null입니다.'}
