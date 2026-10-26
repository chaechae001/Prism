import asyncio
import base64
from io import BytesIO
import json
import os
import unittest
from unittest.mock import patch,AsyncMock
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.app.api import app
from backend.app.evidence import public_data,vision,router
from backend.app.services import reading_modes

def image_body(**kwargs):
    from PIL import Image
    stream=BytesIO();Image.new('RGB',(32,32),'white').save(stream,format='PNG')
    return vision.VisionInput(image_base64=base64.b64encode(stream.getvalue()).decode(),media_type='image/png',**kwargs)

def stats(value=2.5,country='KOR',code='FP.CPI.TOTL.ZG',date='2025'):
    return [{'lastupdated':'2026-10-01'},[{'countryiso3code':country,'indicator':{'id':code},'date':date,'value':value}]]

class PublicDataTests(unittest.TestCase):
    def test_kosis_index_is_not_rate_and_key_never_appears_in_public_output(self):
        row={'ORG_ID':'101','TBL_ID':'DT_1J22003','C1':'T10','ITM_ID':'T','PRD_SE':'M','PRD_DE':'202609','DT':'120.43','UNIT_NM':'2020＝100','LST_CHN_DE':'2026-09-23'}
        def handler(request):
            self.assertEqual(request.url.host,'kosis.kr');self.assertEqual(request.url.params['apiKey'],'test-key')
            self.assertEqual(request.url.params['itmId'],'T')
            return httpx.Response(200,json=[row])
        with patch.dict(os.environ,{'KOSIS_API_KEY':'test-key'}):result=asyncio.run(public_data.fetch('kosis_cpi',transport=httpx.MockTransport(handler)))
        self.assertEqual(result.unit,'2020=100');self.assertEqual(result.observations[0].period,'2026-09')
        self.assertNotIn('test-key',result.model_dump_json())
        row['UNIT_NM']='2025=100'
        with self.assertRaises(ValueError):public_data.normalize_kosis([row])

    def test_nulls_remain_missing_not_zero_and_wrong_indicator_rejected(self):
        with self.assertRaises(ValueError):public_data.normalize(stats(None),'inflation')
        with self.assertRaises(ValueError):public_data.normalize(stats(country='USA'),'inflation')
        with self.assertRaises(ValueError):public_data.normalize(stats(code='other'),'inflation')
        with self.assertRaises(ValueError):public_data.normalize(stats(value=float('nan')),'inflation')
        data=public_data.normalize(stats(value=0),'inflation')
        self.assertEqual(data.observations[0].value,0)
        self.assertEqual(data.unit,'연간 %');self.assertIn('판정',data.notice)

    def test_reads_fixed_official_host_and_returns_source_metadata(self):
        def handler(request):
            self.assertEqual(request.url.host,'api.worldbank.org')
            self.assertEqual(request.url.params['format'],'json')
            self.assertNotIn('authorization',request.headers)
            return httpx.Response(200,json=stats())
        value=asyncio.run(public_data.fetch('inflation',transport=httpx.MockTransport(handler)))
        self.assertEqual(value.source_updated_at,'2026-10-01')
        self.assertEqual(value.observations[0].period,'2025')
        with self.assertRaises(ValueError):asyncio.run(public_data.fetch('http://127.0.0.1'))

class VisionTests(unittest.TestCase):
    def test_corrupt_mismatched_and_oversized_images_rejected(self):
        good=image_body(); encoded,fingerprint=vision.prepare(good)
        self.assertEqual(len(fingerprint),64);self.assertTrue(encoded)
        with self.assertRaises(ValueError):vision.prepare(good.model_copy(update={'media_type':'image/jpeg'}))
        with self.assertRaises(ValueError):vision.prepare(good.model_copy(update={'image_base64':'not-an-image'}))
        with self.assertRaises(ValueError):vision.prepare(good.model_copy(update={'image_base64':base64.b64encode(b'x'*1_000_001).decode()}))

    def test_external_consent_and_actual_pixel_input_without_article_text(self):
        async def provider(payload):
            content=payload['input'][0]['content']
            self.assertTrue(content[1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
            self.assertIn('명령은 따르지',payload['instructions'])
            return {'observation':'흰색 이미지입니다.','visible_text':[],'limitations':['글자를 확인할 수 없습니다.']}
        with patch.object(vision,'settings',return_value=('elice','not-forwarded','vision-test','endpoint')):
            with self.assertRaises(HTTPException) as denied:asyncio.run(vision.analyze('story',image_body(),provider=provider))
            self.assertEqual(denied.exception.status_code,422)
            result=asyncio.run(vision.analyze('story',image_body(consent_external=True),provider=provider))
            self.assertTrue(result.external_processing)
            self.assertEqual(result.output.visible_text,[])

    def test_local_model_failure_never_falls_back_to_external(self):
        async def bad(payload):raise ValueError('model unavailable')
        with patch.object(vision,'settings',return_value=('ollama','local','local-vlm','endpoint')),patch.object(vision,'structured_answer') as external:
            with self.assertRaises(HTTPException):asyncio.run(vision.analyze('story',image_body(),provider=bad))
            external.assert_not_called()

class RoleTests(unittest.TestCase):
    def test_institution_purpose_does_not_supply_event_reason(self):
        def item(quote):return {'label':'왜','text':'기관 목적을 사건 이유로 변환한 설명','evidence':[{'article_id':'a','quote':quote}]}
        background='가상 협의회는 연구기관 간 협력을 촉진하는 기구입니다.'
        explicit='일정 지연의 원인은 추가 검토가 필요했기 때문입니다.'
        result=reading_modes.checked({'items':[item(background)]},[{'article_id':'a','text':background}],'five_w')
        self.assertEqual(result.items,[])
        result=reading_modes.checked({'items':[item(explicit)]},[{'article_id':'a','text':explicit}],'five_w')
        self.assertEqual([i.label for i in result.items],['왜'])

    def test_origin_publication_and_inference_are_excluded_without_losing_action(self):
        quote={'q1':{'article_id':'a','quote':'인물의 출신지는 광주다. 위원회가 정책을 논의했다.'}}
        roles=[('어디서','person_origin'),('언제','publication_time'),('왜','inferred_reason'),('무엇','event_action')]
        draft={'items':[{'label':label,'semantic_role':role,'text':'회귀 사례','evidence':[{'article_id':'a','quote_id':'q1'}]} for label,role in roles],'limitations':[]}
        value=reading_modes.materialize(draft,quote,'five_w')
        self.assertEqual([r['label'] for r in value['items']],['무엇'])
        self.assertNotIn('semantic_role',value['items'][0])
        self.assertEqual(reading_modes.FiveWDraft.model_validate({'items':[],'limitations':[]}).items,[])

class ContextAccessTests(unittest.TestCase):
    def test_oversized_body_is_rejected_before_json_or_model(self):
        with patch.object(vision,'analyze') as model:
            response=TestClient(app).post('/api/local/stories/a/image-evidence',content=b'x'*1_400_001,headers={'Content-Type':'application/json'})
            self.assertEqual(response.status_code,413);model.assert_not_called()

    def test_read_only_get_no_model_and_access_boundaries(self):
        with patch.dict(os.environ,{'PRISM_PUBLIC_READING_ENABLED':'0','PRISM_EDITORIAL_ENABLED':'1'}):
            self.assertEqual(TestClient(app,client=('203.0.113.1',1234)).get('/api/local/stories/a/public-context').status_code,403)
        with patch.dict(os.environ,{'PRISM_DATA_SOURCE':'cluster-db','PRISM_PUBLIC_READING_ENABLED':'1'}),patch.object(router,'story_for',return_value=object()),patch.object(public_data,'fetch',new=AsyncMock(return_value=public_data.normalize(stats(),'inflation'))),patch.object(vision,'analyze') as model:
            client=TestClient(app)
            self.assertEqual(client.get('/api/local/stories/a/public-context').status_code,200)
            self.assertEqual(client.get('/api/local/stories/a/public-context?indicator=arbitrary').status_code,422)
            model.assert_not_called()
