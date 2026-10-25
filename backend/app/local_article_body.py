"""Explicit loopback-only reading preview; never a public full-text feed."""
import asyncio
import os
from fastapi import APIRouter,Request,HTTPException
from pydantic import BaseModel
from .reader_access import reader_access, public_reading_enabled
from .reader_accounts import story_for
from .services.cluster_context import chat_cluster_bodies,ClusterContextError

router=APIRouter(prefix='/api/local/stories',tags=['local-reading-preview'])


class ArticleBody(BaseModel):
    article_id:str
    text:str
    is_excerpt:bool


@router.get('/{story_id}/body',response_model=ArticleBody)
async def body(story_id:str,request:Request):
    if (os.getenv('PRISM_BODY_PREVIEW_ENABLED')!='1' or os.getenv('PRISM_DATA_SOURCE')!='cluster-db'):
        raise HTTPException(403,'본문 미리보기는 허용된 로컬 개발 환경에서만 사용할 수 있습니다.')
    reader_access(request)
    story=await asyncio.to_thread(story_for,story_id)
    try:
        rows=await asyncio.to_thread(chat_cluster_bodies,story)
        selected=next((r for r in rows if r['article_id']==story.articles[0].id),None)
        if not selected: raise ClusterContextError()
    except (ClusterContextError,ValueError):
        raise HTTPException(409,'현재 기사 본문을 표시할 수 없습니다. 원문 링크를 확인해주세요.') from None
    excerpt=selected['text'][:1000 if public_reading_enabled() else 6000].strip()
    return ArticleBody(article_id=selected['article_id'],text=excerpt,is_excerpt=selected['is_excerpt'] or len(excerpt)<len(selected['text']))
