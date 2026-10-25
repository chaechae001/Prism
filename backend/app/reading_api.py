"""Local reading mode API. GET never triggers a billable model call."""
import asyncio
import os
from fastapi import APIRouter,Depends,HTTPException
from .editorial_api import local_editor
from .reader_accounts import story_for
from .services import reading_modes as service

router=APIRouter(prefix='/api/local/stories',tags=['local-reading-modes'],dependencies=[Depends(local_editor)])
lock=asyncio.Lock()

async def run(story_id,mode,generate=False):
    if os.getenv('PRISM_DATA_SOURCE')!='cluster-db':raise HTTPException(409,'DB 뉴스 모드에서 이용할 수 있습니다.')
    try:
        story=await asyncio.to_thread(story_for,story_id)
        if generate:
            if lock.locked():raise HTTPException(409,'다른 읽기 분석을 생성 중입니다. 잠시 후 다시 시도해주세요.')
            async with lock:return await service.generate(story,mode)
        return await asyncio.to_thread(service.read,story,mode)
    except ValueError as exc:raise HTTPException(409,str(exc)) from None

@router.get('/{story_id}/reading/{mode}',response_model=service.ReadingResponse)
async def read(story_id:str,mode:service.Mode):return await run(story_id,mode)

@router.post('/{story_id}/reading/{mode}',response_model=service.ReadingResponse)
async def generate(story_id:str,mode:service.Mode):return await run(story_id,mode,True)
