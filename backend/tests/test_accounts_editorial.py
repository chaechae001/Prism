import copy
import unittest
from unittest.mock import AsyncMock,patch
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.app.api import app
from backend.app import account_auth
from backend.app.services.cluster_quality import evaluate


class AuthTests(unittest.TestCase):
    def test_disabled_accounts_hide_session_and_never_call_supabase(self):
        import httpx
        with patch.dict('os.environ',{'PRISM_ACCOUNTS_ENABLED':'0'}),patch('httpx.AsyncClient.request',new_callable=AsyncMock) as external:
            client=TestClient(app);client.cookies.set(account_auth.ACCESS,'old-local-cookie')
            session=client.get('/api/account/session')
            self.assertEqual(session.json(),{'enabled':False,'configured':False,'user':None})
            for path,body in [('/login',{'email':'reader@example.test','password':'long-password'}),('/signup',{'email':'reader@example.test','password':'long-password'}),('/resend',{'email':'reader@example.test'})]:
                self.assertEqual(client.post('/api/account'+path,json=body).status_code,503)
            self.assertEqual(client.get('/api/account/workspace').status_code,401)
            external.assert_not_awaited()

    def test_mail_rate_limit_preserves_korean_actionable_error(self):
        import asyncio,httpx
        with patch.object(account_auth,'config',return_value=('https://example.supabase.co','test-public')), \
                patch('httpx.AsyncClient.request',new_callable=AsyncMock,return_value=httpx.Response(429,json={'error_code':'over_email_send_rate_limit','msg':'upstream private diagnostics'})):
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(account_auth.auth_call('POST','signup',payload={}))
        self.assertEqual(raised.exception.status_code,429)
        self.assertIn('발송 한도',raised.exception.detail)
        self.assertNotIn('private',raised.exception.detail)

    def test_resend_only_requests_signup_mail_to_allowed_redirect(self):
        with patch.dict('os.environ',{'CORS_ORIGINS':'http://127.0.0.1:5186'}),patch.object(account_auth,'auth_call',new_callable=AsyncMock,return_value={}) as call:
            r=TestClient(app).post('/api/account/resend',headers={'Origin':'http://127.0.0.1:5186'},json={'email':'reader@example.test'})
        self.assertEqual(r.status_code,200)
        self.assertTrue(r.json()['accepted'])
        self.assertIn('이미 인증한 계정',r.json()['notice'])
        self.assertEqual(call.await_args.kwargs['payload']['type'],'signup')

    def test_signup_redirect_is_bound_to_allowed_app_origin(self):
        user={'id':str(uuid4()),'email':'reader@example.test'}
        with patch.dict('os.environ',{'CORS_ORIGINS':'http://127.0.0.1:5186'}),patch.object(account_auth,'auth_call',new_callable=AsyncMock,return_value=user) as call:
            r=TestClient(app).post('/api/account/signup',headers={'Origin':'http://127.0.0.1:5186'},json={'email':'reader@example.test','password':'long-password'})
        self.assertEqual(r.status_code,201)
        self.assertTrue(r.json()['confirmation_required'])
        from urllib.parse import parse_qs,urlsplit
        self.assertEqual(parse_qs(urlsplit(call.await_args.args[1]).query)['redirect_to'],['http://127.0.0.1:5186/'])
    def test_authenticated_dm_saves_exchange_without_forwarding_private_history(self):
        import json
        from backend.app.chat import router as chat
        from backend.app.connection_repository import load_snapshot
        story=load_snapshot('fixture').stories[0]
        owner={'id':str(uuid4()),'email':'reader@example.test'}
        answer=chat.GroundedAnswer(answer='선택 뉴스 설명입니다.',article_ids=[story.articles[0].id])
        chat._clients.clear()
        with patch.dict('os.environ',{'PRISM_DATA_SOURCE':'fixture'}), \
                patch.object(account_auth,'optional_user',new_callable=AsyncMock,return_value=owner), \
                patch.object(chat,'configuration',return_value=True), \
                patch.object(chat,'settings',return_value=('elice','test-key','test-model','https://example.test')), \
                patch.object(chat,'find_story',return_value=story), \
                patch.object(chat,'ask_provider',new_callable=AsyncMock,return_value=answer) as provider, \
                patch('backend.app.reader_accounts.consume_quota') as quota, \
                patch('backend.app.reader_accounts.save_exchange') as save:
            r=TestClient(app).post('/api/social/stories/'+story.id+'/chat',json={'question':'현재 질문','history':[{'role':'user','content':'개인 과거 대화'}]})
        self.assertEqual(r.status_code,200)
        payload=json.loads(provider.await_args.args[0]['input'][0]['content'])
        self.assertEqual(payload['history'],[])
        self.assertEqual(payload['question'],'현재 질문')
        quota.assert_called_once_with(owner['id'])
        self.assertEqual(save.call_args.args[0],owner['id'])

    def test_login_tokens_only_http_only_cookie(self):
        value={'access_token':'private-access','refresh_token':'private-refresh','expires_in':3600,'user':{'id':str(uuid4()),'email':'reader@example.test'}}
        with patch.object(account_auth,'auth_call',new_callable=AsyncMock,return_value=value):
            r=TestClient(app).post('/api/account/login',json={'email':'reader@example.test','password':'long-password'})
        self.assertEqual(r.status_code,200)
        self.assertNotIn('private-access',r.text)
        cookie=';'.join(r.headers.get_list('set-cookie'))
        self.assertIn('HttpOnly',cookie)
        self.assertIn('SameSite=lax',cookie)

    def test_anonymous_workspace_denied_before_db(self):
        with patch('backend.app.reader_accounts._engine') as engine:
            r=TestClient(app).get('/api/account/workspace')
            self.assertEqual(r.status_code,401)
            engine.assert_not_called()

    def test_untrusted_origin_and_default_editorial_denied(self):
        r=TestClient(app).post('/api/account/login',headers={'Origin':'https://untrusted.example'},json={'email':'x@y.test','password':'12345678'})
        self.assertEqual(r.status_code,403)
        with patch.dict('os.environ',{'PRISM_EDITORIAL_ENABLED':'0'}):
            self.assertEqual(TestClient(app).get('/api/editorial/quality').status_code,403)

    def test_logout_clears_expired_session(self):
        from fastapi import HTTPException
        client=TestClient(app);client.cookies.set(account_auth.ACCESS,'expired')
        with patch.object(account_auth,'auth_call',new_callable=AsyncMock,side_effect=HTTPException(401,'expired')):
            r=client.post('/api/account/logout')
        self.assertEqual(r.status_code,200)
        self.assertIn('Max-Age=0',';'.join(r.headers.get_list('set-cookie')))


class QualityTests(unittest.TestCase):
    def fixture(self):
        pairs=[{'a':'a','b':'b','predicted_same_event':True,'same_event':True},
               {'a':'a','b':'c','predicted_same_event':True,'same_event':False},
               {'a':'b','b':'c','predicted_same_event':False,'same_event':True}]
        return {'input_hash':'a'*64,'batch_id':'test','pairs':pairs}

    def test_known_confusion_matrix_and_partial_denominator(self):
        data=self.fixture();r=evaluate(data,data)
        self.assertEqual((r['tp'],r['fp'],r['fn'],r['tn']),(1,1,1,0))
        self.assertEqual(r['f1'],.5)
        data['pairs'][1]['same_event']=None
        self.assertEqual(evaluate(data,data)['label_coverage'],2/3)

    def test_unknown_duplicate_mismatched_and_non_boolean_labels_rejected(self):
        data=self.fixture()
        for change in (lambda x:x.update(input_hash='b'*64),lambda x:x['pairs'].append(x['pairs'][0]),lambda x:x['pairs'][0].update(a='other'),lambda x:x['pairs'][0].update(same_event=1)):
            changed=copy.deepcopy(data);change(changed)
            with self.assertRaises(ValueError): evaluate(data,changed)


class ExpiredSessionTests(unittest.TestCase):
 def test_invalid_refresh_clears_cookies_for_fresh_login(self):
  from fastapi import HTTPException
  client=TestClient(app);client.cookies.set(account_auth.REFRESH,'invalid');client.cookies.set(account_auth.ACCESS,'expired')
  with patch.dict('os.environ',{'PRISM_ACCOUNTS_ENABLED':'1'}),patch.object(account_auth,'auth_call',new_callable=AsyncMock,side_effect=HTTPException(401,'expired')):
   response=client.post('/api/account/refresh')
  self.assertEqual(response.status_code,401);self.assertIn('Max-Age=0',';'.join(response.headers.get_list('set-cookie')))
