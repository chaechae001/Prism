"""Additive source-context endpoints with the existing reader access boundary."""
import asyncio
import os
import httpx
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.routing import APIRoute
from pydantic import BaseModel
from ..reader_access import reading_access
from ..reader_accounts import story_for
from . import public_data,vision

class BoundedImageRoute(APIRoute):
    def get_route_handler(self):
        original=super().get_route_handler()
        async def limited(request:Request):
            if request.method=='POST':
                # Bound the stream before JSON parsing, including chunked bodies.
                raw=bytearray()
                async for part in request.stream():
                    raw.extend(part)
                    if len(raw)>1_400_000:raise HTTPException(413,'이미지 요청 크기 한도를 초과했습니다.')
                request._body=bytes(raw)
            return await original(request)
        return limited

router=APIRouter(prefix='/api/local/stories',tags=['evidence-context'],dependencies=[Depends(reading_access)],route_class=BoundedImageRoute)
_vision_lock=asyncio.Lock()

async def story(identity):
    if os.getenv('PRISM_DATA_SOURCE')!='cluster-db':raise HTTPException(409,'DB 뉴스 모드에서 이용할 수 있습니다.')
    try:return await asyncio.to_thread(story_for,identity)
    except ValueError:raise HTTPException(404,'뉴스를 확인할 수 없습니다.') from None

class ContextResponse(BaseModel):
    story_id:str
    selection:str='user_selected_background'
    data:public_data.PublicData

@router.get('/{story_id}/public-context',response_model=ContextResponse)
async def context(story_id:str,indicator:public_data.Indicator='kosis_cpi'):
    await story(story_id)
    try:return ContextResponse(story_id=story_id,data=await public_data.fetch(indicator))
    except (httpx.HTTPError,ValueError,TypeError,KeyError):raise HTTPException(502,'공식 통계를 불러오지 못했습니다. 잠시 후 다시 조회해주세요.') from None

@router.post('/{story_id}/image-evidence',response_model=vision.VisionResponse)
async def image_evidence(story_id:str,body:vision.VisionInput):
    await story(story_id)
    if _vision_lock.locked():raise HTTPException(409,'다른 이미지 분석을 처리 중입니다. 잠시 후 다시 시도해주세요.')
    try:
        async with _vision_lock:return await vision.analyze(story_id,body)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
