"""Local-only Ollama adapter. Never downloads models or forwards API keys."""
import json
import os
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException


def endpoint():
    url=os.getenv('OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')
    p=urlsplit(url)
    if p.scheme!='http' or p.hostname not in {'127.0.0.1','localhost','::1'} or p.username or p.password or p.path or p.query or p.fragment:
        raise ValueError('Ollama must use a loopback HTTP origin')
    return url


async def answer(payload):
    model=os.getenv('OLLAMA_MODEL','').strip()
    if not model: raise HTTPException(503,'Ollama 모델명을 설정해주세요.')
    body={'model':model,'messages':[{'role':'system','content':payload['instructions']},*payload['input']],
        'stream':False,'keep_alive':0,'format':payload['text']['format']['schema'],
        'options':{'temperature':0,'num_predict':min(payload['max_output_tokens'],2000)}}
    try:
        async with httpx.AsyncClient(timeout=90,follow_redirects=False,trust_env=False) as c:
            response=await c.post(endpoint()+'/api/chat',json=body)
        if response.status_code==404: raise HTTPException(503,'Ollama에 해당 모델이 없습니다. 모델을 준비한 뒤 다시 확인해주세요.')
        if not response.is_success: raise HTTPException(502,'Ollama 요청을 처리하지 못했습니다.')
        value=response.json()
        if value.get('done') is not True or value.get('done_reason')=='length': raise HTTPException(502,'Ollama 답변이 완료되지 않았습니다.')
        from .telemetry import usage
        usage(value.get('prompt_eval_count'),value.get('eval_count'))
        return json.loads(value['message']['content'])
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        raise HTTPException(502,'Ollama 서버·모델·JSON 응답을 확인해주세요.') from None


async def readiness():
    try:
        async with httpx.AsyncClient(timeout=2,follow_redirects=False,trust_env=False) as c:
            r=await c.get(endpoint()+'/api/tags')
        models=[m['name'] for m in r.json().get('models',[]) if isinstance(m.get('name'),str)] if r.is_success else []
        return {'server_ready':r.is_success,'model_ready':os.getenv('OLLAMA_MODEL','') in models,'models':models[:30]}
    except (httpx.HTTPError,ValueError,TypeError,KeyError): return {'server_ready':False,'model_ready':False,'models':[]}
