import asyncio
import hmac
import os
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .models import (Category, Mode, FeedResponse, FeedMeta, StoryResponse, CategoriesResponse,
    CategoryInfo, ErrorResponse, FeedbackRequest, FeedbackResponse, Job, JobRequest, Health)
from .recommendation import rank, cursor_key, decode_cursor, encode_cursor
from .repository import FixtureRepository

if os.getenv('APP_MODE','mock') != 'mock':
    raise RuntimeError('Only mock mode is implemented. Add a Supabase repository and real authentication before production.')

repo = FixtureRepository()
app = FastAPI(title='Prism News API (Mock)', version='1.0.0',
    description='Fictional data only. Internal routes simulate jobs; no external collection or AI calls.',
    responses={code:{'model':ErrorResponse} for code in (401,404,409,422,500,503)})
app.add_middleware(CORSMiddleware,
    allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(','),
    allow_methods=['GET','POST'], allow_headers=['Content-Type','X-Mock-Scenario','X-Admin-Token'])
jobs: dict[str, Job] = {}
state_lock = Lock()
feedback: list[FeedbackRequest] = []

@app.middleware('http')
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers['X-Request-ID'] = request.state.request_id
    return response

def error(request, status, code, message, details=None):
    return JSONResponse(status_code=status,content={'error':{'code':code,'message':message,
        'details':details or [],'request_id':request.state.request_id}})

@app.exception_handler(HTTPException)
async def http_error(request, exc):
    codes={401:'UNAUTHORIZED',404:'NOT_FOUND',409:'CONFLICT',422:'VALIDATION_ERROR',503:'MOCK_ERROR'}
    return error(request, exc.status_code, codes.get(exc.status_code,'HTTP_ERROR'), str(exc.detail))

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    details=[{'loc':list(e['loc']),'message':e['msg'],'type':e['type']} for e in exc.errors()]
    return error(request,422,'VALIDATION_ERROR','요청 값을 확인해주세요.',details)

@app.get('/health',response_model=Health,operation_id='health')
def health(): return Health(dataset_version=repo.dataset_version)

@app.get('/api/v1/categories',response_model=CategoriesResponse,operation_id='listCategories')
def categories():
    names={'politics':'정치','economy':'경제','society':'사회','technology':'기술'}
    return CategoriesResponse(items=[CategoryInfo(id=k,label=v,count=sum(s.category==k for s in repo.all())) for k,v in names.items()])

@app.get('/api/v1/stories',response_model=FeedResponse,operation_id='listStories')
async def stories(request: Request, q: str = Query(default='',max_length=100), category: Category | None = None,
    mode: Mode = 'balanced', diversity: int = Query(default=70,ge=0,le=100),
    limit: int = Query(default=6,ge=1,le=20), cursor: str | None = Query(default=None,max_length=1000),
    scenario: str | None = Header(default=None,alias='X-Mock-Scenario')):
    if scenario == 'error': raise HTTPException(503,'테스트용 API 오류입니다.')
    if scenario == 'slow': await asyncio.sleep(2)
    q=q.strip()
    pool=[s for s in repo.all() if (category is None or s.category==category) and q.casefold() in (' '.join([s.title,s.dek,*s.keywords])).casefold()]
    if scenario == 'empty': pool=[]
    ranked,relaxed=rank(pool,mode,diversity)
    key=cursor_key(repo.dataset_version,q,category,mode,diversity)
    try: offset=decode_cursor(cursor,key,len(ranked)) if cursor else 0
    except ValueError: raise HTTPException(422,'현재 검색 조건과 일치하지 않는 커서입니다.') from None
    page=ranked[offset:offset+limit]
    return FeedResponse(items=page,total=len(ranked),
      next_cursor=encode_cursor(key,offset+limit) if offset+limit<len(ranked) else None,
      meta=FeedMeta(request_id=request.state.request_id,generated_at=datetime.now(timezone.utc),
        dataset_version=repo.dataset_version,mode=mode,diversity=diversity,
        policy_notes=['개인화 없는 데모 순위입니다.','다양성은 주제와 출처 중복을 줄이는 가중치이며 정치 성향 점수가 아닙니다.',
          '정렬은 고정된 fixture 최신성·공익성 예시 값을 사용합니다.'],
        returned_categories=list(dict.fromkeys(i.story.category for i in page)),source_cap_relaxed=relaxed))

@app.get('/api/v1/stories/{story_id}',response_model=StoryResponse,operation_id='getStory')
def story(story_id: str, request: Request):
    value=repo.get(story_id)
    if value is None: raise HTTPException(404,'해당 사건을 찾을 수 없습니다.')
    return StoryResponse(story=value,request_id=request.state.request_id)

@app.post('/api/v1/feedback',response_model=FeedbackResponse,status_code=201,operation_id='createFeedback')
def create_feedback(body: FeedbackRequest, request: Request):
    if repo.get(body.story_id) is None: raise HTTPException(404,'해당 사건을 찾을 수 없습니다.')
    with state_lock: feedback.append(body)
    return FeedbackResponse(id=str(uuid4()),request_id=request.state.request_id)

def require_admin(token):
    expected=os.getenv('MOCK_ADMIN_TOKEN','')
    if not expected or not hmac.compare_digest(token or '',expected):
        raise HTTPException(401,'유효한 관리자 토큰이 필요합니다.')

@app.post('/api/v1/internal/jobs',response_model=Job,status_code=202,operation_id='createJob')
def create_job(body: JobRequest, token: str | None=Header(default=None,alias='X-Admin-Token')):
    require_admin(token)
    job=Job(id=str(uuid4()),stage=body.stage,status='queued',note='시뮬레이션 작업입니다. 실제 수집·AI 처리는 실행하지 않습니다.')
    with state_lock: jobs[job.id]=job
    return job

@app.get('/api/v1/internal/jobs/{job_id}',response_model=Job,operation_id='getJob')
def get_job(job_id: str, token: str | None=Header(default=None,alias='X-Admin-Token')):
    require_admin(token)
    with state_lock:
        job=jobs.get(job_id)
        if not job: raise HTTPException(404,'작업을 찾을 수 없습니다.')
        # Explicit demo transition on polling. A real queue replaces this entire adapter.
        job=job.model_copy(update={'status':{'queued':'running','running':'succeeded'}.get(job.status,job.status)})
        jobs[job_id]=job
    return job
