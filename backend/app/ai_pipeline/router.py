"""Local-only readiness, source-scoped retrieval inspection and durable review."""
import asyncio
from importlib.util import find_spec
import os
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from ..editorial_api import local_editor,lock
from ..reader_accounts import story_for
from ..chat.providers import settings
from ..config import ROOT
from . import schema,telemetry,workflow

router=APIRouter(prefix='/api/editorial/ai',tags=['local-ai-tools'],dependencies=[Depends(local_editor)])


class WorkflowInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    story_id:str=Field(min_length=1,max_length=100)


class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    approve:bool


class SearchInput(WorkflowInput):
    question:str=Field(min_length=1,max_length=2000)


@router.get('/status')
async def readiness():
    from .ollama import readiness as ollama_status
    path=Path(os.getenv('PRISM_E5_MODEL_DIR',str(ROOT/'.models/multilingual-e5-small')))
    ready=all((path/name).is_file() for name in ('tokenizer.json','onnx/model_quantized.onnx'))
    try:storage=await asyncio.to_thread(schema.status)
    except Exception:storage={'ready':False,'tables':0}
    ollama=await ollama_status()
    embedding_provider=os.getenv('PRISM_EMBEDDING_PROVIDER','e5')
    embedding_model=os.getenv('OLLAMA_EMBED_MODEL','bge-m3:latest') if embedding_provider=='ollama' else 'multilingual-e5-small'
    embedding_ready=(embedding_model.startswith('bge-m3:') and embedding_model in ollama['models'] and storage.get('bge_dimensions_ready',False)) if embedding_provider=='ollama' else ready if embedding_provider=='e5' else False
    return {'embedding_provider':embedding_provider,'embedding_model':embedding_model,'embedding_ready':embedding_ready,'provider':settings()[0],'model':settings()[2],'rag_enabled':os.getenv('PRISM_RAG_ENABLED')=='1',
        'embedding_files_ready':ready,'storage':storage,'langchain_enabled':os.getenv('PRISM_LANGCHAIN_ENABLED')=='1',
        'langchain_installed':find_spec('langchain_core') is not None,'langgraph_installed':find_spec('langgraph') is not None,
        'metrics_enabled':os.getenv('PRISM_LLM_METRICS_ENABLED')=='1','opik_export_enabled':os.getenv('PRISM_OPIK_ENABLED')=='1',
        'ollama':ollama,'fine_tuning':'reviewed_dataset_preparation_only'}


@router.get('/metrics')
async def metrics():
    if not (await asyncio.to_thread(schema.status))['ready']:raise HTTPException(503,'AI 관측 스키마를 먼저 준비해주세요.')
    return await asyncio.to_thread(telemetry.report)


@router.post('/retrieve')
async def retrieve(body:SearchInput):
    if not (await asyncio.to_thread(schema.status))['ready']:raise HTTPException(503,'검색 스키마를 먼저 준비해주세요.')
    try:
        from .retrieval import retrieve as search
        story=await asyncio.to_thread(story_for,body.story_id)
        rows=await asyncio.to_thread(search,story,body.question)
        return {'chunks':[{'article_id':r['article_id'],'chunk_id':r['chunk_id'],'start':r['start'],'end':r['end'],'characters':len(r['text'])} for r in rows],
            'notice':'선택한 사건의 허용된 기사 청크만 조회했습니다. 이 점검은 LLM을 호출하지 않습니다.'}
    except (ValueError,ImportError):raise HTTPException(409,'임베딩 모델·의존성·현재 기사 본문과 검색 설정을 확인해주세요.') from None


@router.post('/workflows')
async def create_workflow(body:WorkflowInput):
    if find_spec('langgraph') is None:raise HTTPException(503,'LangGraph 선택 의존성이 필요합니다.')
    if lock.locked():raise HTTPException(409,'다른 요약 작업이 진행 중입니다.')
    try:
        async with lock:return await workflow.start(body.story_id)
    except ValueError:raise HTTPException(409,'현재 기사와 요약 제공자 설정을 확인해주세요.') from None


@router.get('/workflows/{identity}')
async def state(identity:UUID):
    try:return await workflow.inspect(str(identity))
    except ValueError:raise HTTPException(404,'작업 상태를 찾을 수 없습니다.') from None


@router.post('/workflows/{identity}/resume')
async def resume(identity:UUID,body:Decision):
    try:
        async with lock:return await workflow.resume(str(identity),body.approve)
    except ValueError:raise HTTPException(409,'검토 대기 상태와 원문 버전을 확인해주세요.') from None


@router.post('/workflows/{identity}/retry')
async def retry(identity:UUID):
    try:
        async with lock:return await workflow.retry(str(identity))
    except ValueError:raise HTTPException(409,'실패한 작업 상태와 원문 버전을 확인해주세요.') from None
