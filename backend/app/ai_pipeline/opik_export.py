"""Manually export approved operational metadata, never prompts or news bodies."""
from datetime import timedelta
from functools import lru_cache
import os
from urllib.parse import urlsplit


def target():
    value=os.getenv('OPIK_URL_OVERRIDE','http://127.0.0.1:5174/api').rstrip('/')
    p=urlsplit(value)
    local=p.scheme=='http' and p.hostname in {'127.0.0.1','localhost','::1'}
    cloud=p.scheme=='https' and p.hostname=='www.comet.com' and p.path=='/opik/api'
    if p.username or p.password or p.query or p.fragment or not(local or cloud): raise ValueError('허용된 로컬 Opik 또는 공식 클라우드 주소를 사용해주세요.')
    if cloud and not os.getenv('OPIK_API_KEY'): raise ValueError('Opik 클라우드 키가 설정되지 않았습니다.')
    return value


@lru_cache(maxsize=1)
def client():
    host=target()
    # Do not read an implicit personal config or activate automatic integrations.
    os.environ['OPIK_SENTRY_ENABLE']='false'
    os.environ['OPIK_ANALYTICS_ENABLE']='false'
    from opik import Opik
    return Opik(host=host,api_key=os.getenv('OPIK_API_KEY',''),project_name=os.getenv('OPIK_PROJECT_NAME','prism'),workspace=os.getenv('OPIK_WORKSPACE','default'),_show_misconfiguration_message=False)


def export(record):
    if os.getenv('PRISM_OPIK_ENABLED')!='1':return False
    c=client()
    metadata={key:record[key] for key in ('task','provider','model','prompt_version','input_hash','status','error_type','elapsed_ms','input_tokens','output_tokens')}
    c.trace(name='prism.'+record['task'],input={'fingerprint':record['input_hash']},output={'status':record['status']},metadata=metadata,
        start_time=record['created_at'],end_time=record['created_at']+timedelta(milliseconds=record['elapsed_ms']))
    c.flush()
    return True
