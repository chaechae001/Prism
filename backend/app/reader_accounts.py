"""Owner-scoped persistence. User identity comes only from verified Supabase Auth."""
import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from .account_auth import required_user, check_origin
from .cluster_store.repository import _engine
from .connection_repository import load_snapshot, resolve_story

router = APIRouter(prefix='/api/account', tags=['account-storage'])


class CommentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    story_id: str = Field(min_length=1,max_length=100)
    text: str = Field(min_length=1,max_length=1000)


def story_for(identity):
    story=resolve_story(load_snapshot(),identity)
    if not story: raise HTTPException(404,'해당 뉴스를 찾을 수 없습니다.')
    return story


def workspace(user_id, *, engine=None):
    with _engine(engine).connect() as c,c.begin():
        c.execute(text('SET TRANSACTION READ ONLY'))
        params={'u':user_id}
        bookmarks=c.execute(text('SELECT story_id FROM private.prism_reader_bookmarks WHERE user_id=:u ORDER BY created_at DESC LIMIT 500'),params).scalars().all()
        comments=c.execute(text('SELECT id,story_id,text,created_at FROM private.prism_reader_comments WHERE user_id=:u ORDER BY created_at DESC LIMIT 500'),params).mappings().all()
        threads=c.execute(text('SELECT story_id,title,category FROM private.prism_reader_threads WHERE user_id=:u ORDER BY updated_at DESC LIMIT 50'),params).mappings().all()
        messages=c.execute(text('''SELECT * FROM (SELECT id,story_id,role,text,article_ids,model,created_at,
            row_number() OVER (PARTITION BY story_id ORDER BY created_at DESC,id DESC) AS n
            FROM private.prism_reader_messages WHERE user_id=:u) x WHERE n<=100 ORDER BY created_at,id'''),params).mappings().all()
    return {'bookmarks':list(bookmarks),'comments':[{'id':str(r['id']),'storyId':r['story_id'],'text':r['text'],'createdAt':r['created_at'].isoformat()} for r in comments],
        'threads':[{'id':r['story_id'],'title':r['title'],'category':r['category'],'messages':[
            {'id':str(m['id']),'role':m['role'],'text':m['text'],'articleIds':m['article_ids'],'model':m['model'],'createdAt':m['created_at'].isoformat()}
            for m in messages if m['story_id']==r['story_id']]} for r in threads]}


def bookmark(user_id,identity,save,*,engine=None):
    with _engine(engine).begin() as c:
        if save:
            count=c.execute(text('SELECT count(*) FROM private.prism_reader_bookmarks WHERE user_id=:u'),{'u':user_id}).scalar_one()
            if count>=500: raise HTTPException(409,'북마크는 최대 500개까지 저장할 수 있습니다.')
            c.execute(text('INSERT INTO private.prism_reader_bookmarks(user_id,story_id) VALUES (:u,:s) ON CONFLICT DO NOTHING'),{'u':user_id,'s':identity})
        else:
            c.execute(text('DELETE FROM private.prism_reader_bookmarks WHERE user_id=:u AND story_id=:s'),{'u':user_id,'s':identity})


def save_thread(user_id,story,*,engine=None):
    with _engine(engine).begin() as c:
        _thread(c,user_id,story)


def _thread(c,user_id,story):
    c.execute(text('''INSERT INTO private.prism_reader_threads(user_id,story_id,title,category) VALUES (:u,:s,:t,:cat)
        ON CONFLICT(user_id,story_id) DO UPDATE SET title=excluded.title,category=excluded.category,updated_at=now()'''),
        {'u':user_id,'s':story.id,'t':story.title,'cat':story.category})


def consume_quota(user_id,*,engine=None):
    with _engine(engine).begin() as c:
        n=c.execute(text('''INSERT INTO private.prism_reader_usage(user_id,bucket,requests) VALUES (:u,date_trunc('hour',now()),1)
            ON CONFLICT(user_id,bucket) DO UPDATE SET requests=prism_reader_usage.requests+1
            WHERE prism_reader_usage.requests<30 RETURNING requests'''),{'u':user_id}).scalar_one_or_none()
        if n is None: raise HTTPException(429,'계정당 한 시간에 최대 30번 질문할 수 있습니다.')


def save_exchange(user_id,story,question,result,model,*,engine=None):
    with _engine(engine).begin() as c:
        _thread(c,user_id,story)
        for offset,role,body,ids in [(0,'user',question,[]),(1,'assistant',result.answer,result.article_ids)]:
            c.execute(text('''INSERT INTO private.prism_reader_messages(user_id,story_id,role,text,article_ids,model,created_at)
                VALUES (:u,:s,:r,:t,cast(:ids AS jsonb),:model,clock_timestamp()+:offset*interval '1 millisecond')'''),
                {'u':user_id,'s':story.id,'r':role,'t':body,'ids':json.dumps(ids),'model':model if role=='assistant' else None,'offset':offset})


@router.get('/workspace')
async def read_workspace(request:Request):
    user=await required_user(request)
    return await asyncio.to_thread(workspace,user['id'])


@router.put('/bookmarks/{story_id}')
async def put_bookmark(story_id:str,request:Request):
    check_origin(request);user=await required_user(request)
    await asyncio.to_thread(story_for,story_id)
    await asyncio.to_thread(bookmark,user['id'],story_id,True)
    return {'saved':True}


@router.delete('/bookmarks/{story_id}')
async def delete_bookmark(story_id:str,request:Request):
    check_origin(request);user=await required_user(request)
    await asyncio.to_thread(bookmark,user['id'],story_id,False)
    return {'saved':False}


@router.post('/comments',status_code=201)
async def add_comment(body:CommentInput,request:Request):
    check_origin(request);user=await required_user(request)
    await asyncio.to_thread(story_for,body.story_id)
    if not body.text.strip(): raise HTTPException(422,'댓글 내용을 입력해주세요.')
    def insert():
        with _engine(None).begin() as c:
            c.execute(text('INSERT INTO private.prism_reader_comments(user_id,story_id,text) VALUES (:u,:s,:t)'),{'u':user['id'],'s':body.story_id,'t':body.text.strip()})
    await asyncio.to_thread(insert)
    return {'saved':True}


@router.delete('/comments/{comment_id}')
async def remove_comment(comment_id:UUID,request:Request):
    check_origin(request);user=await required_user(request)
    def delete():
        with _engine(None).begin() as c:
            c.execute(text('DELETE FROM private.prism_reader_comments WHERE id=:id AND user_id=:u'),{'id':comment_id,'u':user['id']})
    await asyncio.to_thread(delete)
    return {'deleted':True}


@router.post('/threads/{story_id}')
async def open_thread(story_id:str,request:Request):
    check_origin(request);user=await required_user(request)
    story=await asyncio.to_thread(story_for,story_id)
    await asyncio.to_thread(save_thread,user['id'],story)
    return {'saved':True}


def delete_thread(user_id,story_id,*,engine=None):
    # 메시지는 소유자+사건 FK의 ON DELETE CASCADE로 함께 지워집니다.
    with _engine(engine).begin() as c:
        c.execute(text('DELETE FROM private.prism_reader_threads WHERE user_id=:u AND story_id=:s'),{'u':user_id,'s':story_id})


@router.delete('/threads/{story_id}')
async def remove_thread(story_id:str,request:Request):
    check_origin(request);user=await required_user(request)
    await asyncio.to_thread(delete_thread,user['id'],story_id)
    return {'deleted':True}
