"""Loopback-only editorial tools, separate from public news APIs."""
import asyncio
import os
from uuid import UUID
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, Field, ConfigDict
from .account_auth import check_origin
from .reader_accounts import story_for
from .services import editorial
from .services.cluster_quality import assessment,evaluate
from .connection_repository import load_snapshot


def local_editor(request:Request):
    if os.getenv('PRISM_EDITORIAL_ENABLED')!='1' or not request.client or request.client.host not in {'127.0.0.1','::1','testclient'}:
        raise HTTPException(403,'편집 도구는 허용된 로컬 개발 환경에서만 사용할 수 있습니다.')
    check_origin(request)


router=APIRouter(prefix='/api/editorial',tags=['local-editorial'],dependencies=[Depends(local_editor)])
lock=asyncio.Lock()


class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    approve:bool


class Labels(BaseModel):
    batch_id:str=Field(max_length=200)
    input_hash:str=Field(pattern='^[a-f0-9]{64}$')
    pairs:list[dict]=Field(max_length=125000)


@router.get('/drafts')
async def drafts():
    return {'items':await asyncio.to_thread(editorial.drafts)}


@router.get('/candidates')
async def candidates():
    snapshot=await asyncio.to_thread(load_snapshot)
    return {'items':[{'id':s.id,'title':s.title,'article_count':len(s.articles),'summary_status':s.summary.status} for s in snapshot.stories]}


@router.post('/stories/{story_id}/generate')
async def generate(story_id:str):
    if os.getenv('PRISM_DATA_SOURCE')!='cluster-db': raise HTTPException(409,'DB 군집 모드에서 요약을 생성할 수 있습니다.')
    if lock.locked(): raise HTTPException(409,'다른 요약을 생성하고 있습니다. 잠시 후 다시 시도해주세요.')
    try:
        async with lock:
            story=await asyncio.to_thread(story_for,story_id)
            return await editorial.generate(story)
    except ValueError as exc: raise HTTPException(409,str(exc)) from None


@router.post('/drafts/{identity}/review')
async def review(identity:UUID,body:Review):
    try: return await asyncio.to_thread(editorial.review,identity,body.approve)
    except ValueError as exc: raise HTTPException(409,str(exc)) from None


@router.get('/quality')
async def quality():
    try: return await asyncio.to_thread(assessment,namespace=os.getenv('PRISM_CLUSTER_NAMESPACE','scheduled-local-test'))
    except ValueError as exc: raise HTTPException(409,str(exc)) from None


@router.post('/quality/evaluate')
async def evaluate_labels(body:Labels):
    try:
        current=await quality()
        return evaluate(current,body.model_dump())
    except ValueError as exc: raise HTTPException(422,str(exc)) from None
