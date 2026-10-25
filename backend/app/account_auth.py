"""Supabase Auth proxy. Tokens stay in HttpOnly cookies, never JSON or localStorage."""
import os
import base64
import json
import logging
from urllib.parse import urlsplit, urlencode
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix='/api/account',tags=['account'])
ACCESS = 'prism_access'
REFRESH = 'prism_refresh'


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3,max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: str = Field(min_length=8,max_length=128)


class EmailRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    email:str=Field(min_length=3,max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class MailRequestResult(BaseModel):
    accepted:bool
    notice:str


class PublicUser(BaseModel):
    id:str
    email:str


class Session(BaseModel):
    enabled:bool=True
    configured:bool
    user:PublicUser|None


class LoginResult(BaseModel):
    user:PublicUser


class SignupResult(LoginResult):
    confirmation_required:bool


def accounts_enabled():
    return os.getenv('PRISM_ACCOUNTS_ENABLED','1')=='1'


def config():
    url = os.getenv('SUPABASE_URL','').rstrip('/')
    key = os.getenv('SUPABASE_PUBLISHABLE_KEY','')
    if key.startswith('sb_secret_'):
        raise HTTPException(503,'로그인에는 publishable/anon 공개 키를 사용해주세요.')
    if key.count('.')==2:
        try:
            claims=json.loads(base64.urlsafe_b64decode(key.split('.')[1]+'==='))
            if claims.get('role')!='anon': raise ValueError()
        except (ValueError,TypeError):
            raise HTTPException(503,'로그인에는 publishable/anon 공개 키를 사용해주세요.') from None
    p = urlsplit(url)
    if (p.scheme!='https' or not p.hostname or not p.hostname.endswith('.supabase.co')
            or p.username or p.password or p.path or p.query or p.fragment or not key):
        raise HTTPException(503,'Supabase 로그인 연결 설정을 준비하고 있습니다.')
    return url,key


def check_origin(request):
    origin = request.headers.get('origin')
    allowed = {s.strip() for s in os.getenv('CORS_ORIGINS','http://127.0.0.1:5186').split(',')}
    if origin and origin not in allowed:
        raise HTTPException(403,'허용되지 않은 요청 출처입니다.')


def confirmation_redirect(request):
    """Use only a server-allowed app origin; never accept a client redirect URL."""
    allowed=[s.strip().rstrip('/') for s in os.getenv('CORS_ORIGINS','http://127.0.0.1:5186').split(',') if s.strip()]
    origin=request.headers.get('origin','').rstrip('/')
    target=origin if origin in allowed else (allowed[0] if allowed else '')
    parsed=urlsplit(target)
    if (parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise HTTPException(503,'인증 후 돌아올 앱 주소 설정을 확인해주세요.')
    return target+'/'


async def auth_call(method,path,*,payload=None,token=None):
    if not accounts_enabled():
        raise HTTPException(503,'테스트 중에는 계정 기능을 사용하지 않습니다.')
    url,key = config()
    headers = {'apikey':key,'Content-Type':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    try:
        async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
            response = await client.request(method,url+'/auth/v1/'+path,json=payload,headers=headers)
        if response.status_code>=400:
            try:
                error=response.json()
                code=error.get('error_code') or error.get('code')
            except (ValueError,AttributeError): code=None
            known={
                'over_email_send_rate_limit':(429,'Supabase 인증 메일 발송 한도에 도달했습니다. 잠시 후 다시 시도하거나 관리자에게 SMTP 설정을 요청해주세요.'),
                'over_request_rate_limit':(429,'인증 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.'),
                'email_address_not_authorized':(403,'현재 메일 서버에서 이 주소로 발송할 수 없습니다. Supabase의 사용자 지정 SMTP 설정을 확인해주세요.'),
                'email_address_invalid':(422,'수신 가능한 이메일 주소를 확인해주세요.'),
                'user_already_exists':(409,'이미 가입된 계정입니다. 회원가입 대신 로그인해주세요.'),
                'email_not_confirmed':(401,'이메일 인증이 필요합니다. 인증 메일을 확인하거나 다시 요청해주세요.'),
                'unexpected_failure':(503,'인증 서버 또는 메일 발송 설정에 문제가 있습니다. Supabase Auth 로그와 SMTP 설정을 확인해주세요.'),
            }
            if code in known:
                logging.getLogger('prism.auth').warning('인증 요청 실패: code=%s status=%s',code,response.status_code)
                raise HTTPException(*known[code])
            if response.status_code==429:
                raise HTTPException(429,'인증 메일 또는 요청 한도에 도달했습니다. 잠시 후 다시 시도해주세요.')
            raise HTTPException(401 if response.status_code in (400,401,403) else 503,
                '이메일·비밀번호 또는 이메일 인증 상태를 확인해주세요.' if path.startswith('token') else '인증 요청을 완료하지 못했습니다.')
        return response.json() if response.content else {}
    except (httpx.HTTPError,ValueError):
        raise HTTPException(503,'로그인 서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.') from None


def public_user(user):
    try: identity = str(UUID(user['id']))
    except (KeyError,TypeError,ValueError): raise HTTPException(401,'로그인을 다시 확인해주세요.') from None
    return {'id':identity,'email':user.get('email','')}


async def optional_user(request):
    if not accounts_enabled(): return None
    token = request.cookies.get(ACCESS)
    if not token: return None
    return public_user(await auth_call('GET','user',token=token))


async def required_user(request):
    user = await optional_user(request)
    if not user: raise HTTPException(401,'로그인 후 이용해주세요.')
    return user


def set_session(response,value):
    if not value.get('access_token') or not value.get('refresh_token'):
        raise HTTPException(401,'인증 세션을 받지 못했습니다.')
    secure = os.getenv('PRISM_COOKIE_SECURE','0')=='1'
    for name,token,age in [(ACCESS,value['access_token'],min(int(value.get('expires_in',3600)),7200)),
                           (REFRESH,value['refresh_token'],30*86400)]:
        response.set_cookie(name,token,max_age=age,httponly=True,secure=secure,samesite='lax',path='/api')


@router.get('/session',response_model=Session)
async def session(request:Request,response:Response):
    if not accounts_enabled():
        response.delete_cookie(ACCESS,path='/api');response.delete_cookie(REFRESH,path='/api')
        return {'enabled':False,'configured':False,'user':None}
    try: config(); configured=True
    except HTTPException: configured=False
    if configured and not request.cookies.get(ACCESS) and request.cookies.get(REFRESH):
        raise HTTPException(401,'로그인 세션을 갱신해주세요.')
    try:user=await optional_user(request) if configured else None
    except HTTPException as exc:
        if exc.status_code!=401 or request.cookies.get(REFRESH):raise
        response.delete_cookie(ACCESS,path='/api');user=None
    return {'configured':configured,'user':user}


@router.post('/login',response_model=LoginResult)
async def login(body:Credentials,request:Request,response:Response):
    check_origin(request)
    value = await auth_call('POST','token?grant_type=password',payload=body.model_dump())
    set_session(response,value)
    return {'user':public_user(value.get('user',{}))}


@router.post('/signup',status_code=201,response_model=SignupResult)
async def signup(body:Credentials,request:Request,response:Response):
    check_origin(request)
    value = await auth_call('POST','signup?'+urlencode({'redirect_to':confirmation_redirect(request)}),payload=body.model_dump())
    if value.get('access_token'): set_session(response,value)
    return {'user':public_user(value.get('user',value)), 'confirmation_required':not bool(value.get('access_token'))}


@router.post('/resend',response_model=MailRequestResult)
async def resend(body:EmailRequest,request:Request):
    check_origin(request)
    await auth_call('POST','resend?'+urlencode({'redirect_to':confirmation_redirect(request)}),payload={'type':'signup','email':body.email})
    return {'accepted':True,'notice':'인증 메일을 요청했습니다. 미인증 계정이라면 받은편지함·스팸함을 확인해주세요. 이미 인증한 계정은 로그인해주세요.'}


@router.post('/refresh',response_model=LoginResult)
async def refresh(request:Request,response:Response):
    check_origin(request)
    token = request.cookies.get(REFRESH)
    try:
        if not token:raise HTTPException(401,'다시 로그인해주세요.')
        value=await auth_call('POST','token?grant_type=refresh_token',payload={'refresh_token':token})
    except HTTPException as exc:
        if exc.status_code!=401:raise
        cleared=JSONResponse(status_code=401,content={'detail':'로그인 세션이 만료되었습니다. 다시 로그인해주세요.'})
        cleared.delete_cookie(ACCESS,path='/api');cleared.delete_cookie(REFRESH,path='/api')
        return cleared
    set_session(response,value)
    return {'user':public_user(value.get('user',{}))}


@router.post('/logout')
async def logout(request:Request,response:Response):
    check_origin(request)
    token = request.cookies.get(ACCESS)
    if token and accounts_enabled():
        try:
            await auth_call('POST','logout?scope=local',token=token)
        except HTTPException:
            pass  # Local logout must also clear an expired or unreachable session.
    response.delete_cookie(ACCESS,path='/api');response.delete_cookie(REFRESH,path='/api')
    return {'logged_out':True}
