import asyncio
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock,Mock,patch
from uuid import uuid4
import httpx

from backend.app.ai_pipeline import ollama,datasets,telemetry
from backend.app.chat.router import GroundedAnswer


class ProviderTests(unittest.TestCase):
    def test_ollama_never_accepts_remote_target_or_sends_api_keys(self):
        with patch.dict(os.environ,{'OLLAMA_URL':'https://attacker.example'}):
            with self.assertRaises(ValueError):ollama.endpoint()
        payload={'instructions':'한국어로 답하세요','input':[{'role':'user','content':'질문'}],'max_output_tokens':1800,'text':{'format':{'schema':{'type':'object'}}}}
        response=httpx.Response(200,json={'done':True,'done_reason':'stop','message':{'content':'{"answer":"설명","article_ids":["a"]}'},'prompt_eval_count':5,'eval_count':4})
        with patch.dict(os.environ,{'OLLAMA_URL':'http://127.0.0.1:11434','OLLAMA_MODEL':'test-model','ELICE_API_KEY':'do-not-forward'}),patch('httpx.AsyncClient.post',new_callable=AsyncMock,return_value=response) as call:
            value=asyncio.run(ollama.answer(payload))
        self.assertEqual(value['article_ids'],['a'])
        self.assertNotIn('do-not-forward',str(call.call_args))
        self.assertNotIn('headers',call.call_args.kwargs)

    @unittest.skipUnless(importlib.util.find_spec('langchain_core'),'Optional LangChain dependency')
    def test_langchain_runs_provider_and_strict_parser(self):
        from backend.app.ai_pipeline.chain import invoke
        provider=AsyncMock(return_value={'answer':'설명','article_ids':['a']})
        answer=asyncio.run(invoke({'test':True},provider,GroundedAnswer))
        self.assertEqual(answer.answer,'설명');provider.assert_awaited_once()
        with self.assertRaises(Exception):asyncio.run(invoke({},AsyncMock(return_value={'answer':'설명','article_ids':[],'extra':'bad'}),GroundedAnswer))


class MetricsTests(unittest.TestCase):
    def test_trace_records_usage_but_never_prompt_or_answer(self):
        async def run():
            async with telemetry.trace('chat',{'question':'PRIVATE QUESTION'},'elice','test','v1'):
                telemetry.usage(100,50)
        with patch.dict(os.environ,{'PRISM_LLM_METRICS_ENABLED':'1','PRISM_OPIK_ENABLED':'0'}),patch.object(telemetry,'save') as save:
            asyncio.run(run())
        record=save.call_args.args[0]
        self.assertNotIn('PRIVATE',str(record));self.assertEqual(record['input_tokens'],100)
        self.assertEqual(record['status'],'ok');self.assertIsNone(record['estimated_cost_usd'])

    def test_cost_unknown_is_not_zero_and_failed_calls_preserve_error(self):
        self.assertIsNone(telemetry.estimate({'provider':'ollama'}))
        async def run():
            async with telemetry.trace('summary',{},'elice','test','v1'):raise ValueError('PRIVATE BODY')
        with patch.dict(os.environ,{'PRISM_LLM_METRICS_ENABLED':'1','PRISM_OPIK_ENABLED':'0'}),patch.object(telemetry,'save') as save:
            with self.assertRaises(ValueError):asyncio.run(run())
        self.assertEqual(save.call_args.args[0]['error_type'],'ValueError')
        self.assertNotIn('PRIVATE',str(save.call_args))

    def test_opik_is_opt_in_and_rejects_unknown_export_host(self):
        from backend.app.ai_pipeline import opik_export
        with patch.dict(os.environ,{'PRISM_OPIK_ENABLED':'0'}),patch.object(opik_export,'client') as c:
            self.assertFalse(opik_export.export({}));c.assert_not_called()
        with patch.dict(os.environ,{'OPIK_URL_OVERRIDE':'https://unknown.example/api'}):
            with self.assertRaises(ValueError):opik_export.target()

    def test_opik_export_payload_contains_only_approved_metadata(self):
        from datetime import datetime,timezone
        from backend.app.ai_pipeline import opik_export
        record={'task':'chat','provider':'elice','model':'test','prompt_version':'v1','input_hash':'a'*64,'status':'ok','error_type':None,'elapsed_ms':5,'input_tokens':2,'output_tokens':3,'created_at':datetime.now(timezone.utc),'question':'PRIVATE QUESTION','body':'PRIVATE BODY'}
        client=Mock()
        with patch.dict(os.environ,{'PRISM_OPIK_ENABLED':'1'}),patch.object(opik_export,'client',return_value=client):
            self.assertTrue(opik_export.export(record))
        self.assertNotIn('PRIVATE',str(client.trace.call_args));client.flush.assert_called_once()


class DatasetTests(unittest.TestCase):
    def data(self):return [{'id':str(i),'event_group':'event-'+str(i),'input':'기사 '+str(i),'answer':'검토 정답 '+str(i),'human_reviewed':True,'approved_for_training':True} for i in range(6)]
    def test_event_splits_are_disjoint_and_no_training_starts(self):
        output,manifest=datasets.prepare(self.data());groups=manifest['groups']
        self.assertFalse(set(groups['train'])&set(groups['test']))
        self.assertFalse(manifest['training_started']);self.assertEqual(sum(len(v) for v in output.values()),6)
    def test_missing_review_or_training_permission_and_duplicate_inputs_fail(self):
        for key in ('human_reviewed','approved_for_training'):
            data=self.data();data[0][key]=False
            with self.assertRaises(ValueError):datasets.prepare(data)
        data=self.data();data[1]['input']=data[0]['input']
        with self.assertRaises(ValueError):datasets.prepare(data)
    def test_regression_scores_do_not_claim_fact_accuracy(self):
        result=datasets.evaluate([{'id':'x','answer':'기간은 3개월','expected_facts':['3개월'],'forbidden_facts':['확정 예산'],'article_ids':['outside'],'allowed_article_ids':['a']}])
        self.assertFalse(result['cases'][0]['citations_valid']);self.assertEqual(result['cases'][0]['expected_fact_hits'],1)


@unittest.skipUnless(importlib.util.find_spec('langgraph'),'Optional LangGraph dependency')
class WorkflowTests(unittest.TestCase):
    def test_billable_generation_is_only_retried_explicitly(self):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langgraph.types import Command
        from backend.app.ai_pipeline.workflow import graph
        generate=AsyncMock(side_effect=[ValueError('temporary'),{'id':str(uuid4())}]);publish=Mock();validate=Mock(return_value={'hash':'a'*64})
        async def run(path):
            config={'configurable':{'thread_id':'unit-retry'}}
            async with AsyncSqliteSaver.from_conn_string(path) as c:
                app=graph(c,generate=generate,validate=validate,publish=publish)
                with self.assertRaises(ValueError):await app.ainvoke({'story_id':'news'},config)
                self.assertEqual(generate.await_count,1);publish.assert_not_called()
                pending=await app.ainvoke(None,config)
                self.assertIn('__interrupt__',pending);self.assertEqual(generate.await_count,2)
                result=await app.ainvoke(Command(resume=False),config)
                self.assertEqual(result['phase'],'rejected')
        with TemporaryDirectory() as folder:asyncio.run(run(str(Path(folder)/'retry.sqlite')))
        self.assertFalse(publish.call_args.args[1])

    def test_review_wait_survives_restart_and_publishes_only_on_resume(self):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langgraph.types import Command
        from backend.app.ai_pipeline.workflow import graph
        generate=AsyncMock(return_value={'id':str(uuid4())});publish=Mock();validate=Mock(return_value={'hash':'a'*64})
        async def run(path):
            config={'configurable':{'thread_id':'unit-review'}}
            async with AsyncSqliteSaver.from_conn_string(path) as c:
                value=await graph(c,generate=generate,validate=validate,publish=publish).ainvoke({'story_id':'news'},config)
                self.assertIn('__interrupt__',value);publish.assert_not_called()
            async with AsyncSqliteSaver.from_conn_string(path) as c:
                value=await graph(c,generate=generate,validate=validate,publish=publish).ainvoke(Command(resume=True),config)
                self.assertEqual(value['phase'],'published')
        with TemporaryDirectory() as folder:asyncio.run(run(str(Path(folder)/'checkpoints.sqlite')))
        generate.assert_awaited_once();publish.assert_called_once()


@unittest.skipUnless(importlib.util.find_spec('numpy'),'Optional embedding dependency')
class EmbeddingTests(unittest.TestCase):
    def test_bge_uses_installed_digest_and_preserves_chunk_offsets(self):
        import numpy as np
        from backend.app.ai_pipeline.embeddings import OllamaEmbedding
        tags=httpx.Response(200,json={'models':[{'name':'bge-m3:latest','digest':'abc'}]},request=httpx.Request('GET','http://localhost'))
        vectors=httpx.Response(200,json={'embeddings':[[1.0]*1024]},request=httpx.Request('POST','http://localhost'))
        with patch.dict(os.environ,{'OLLAMA_URL':'http://127.0.0.1:11434','OLLAMA_EMBED_MODEL':'bge-m3:latest'}),patch('httpx.Client.get',return_value=tags),patch('httpx.Client.post',return_value=vectors) as post:
            enc=OllamaEmbedding();text='기사 본문'*400;spans=enc.chunks(text)
            self.assertEqual(spans[0],(0,600));self.assertEqual(spans[1][0],520)
            self.assertEqual(spans[-1][1],len(text));self.assertIn('abc',enc.model_id)
            result=enc.encode(['질문'],query=True)
            self.assertEqual(result.shape,(1,1024));self.assertAlmostEqual(float(np.linalg.norm(result[0])),1,places=5)
            self.assertEqual(post.call_args.kwargs['json']['input'],['질문'])
            self.assertFalse(post.call_args.kwargs['json']['truncate'])
    def test_vector_rejects_bad_dimension_or_non_unit_values(self):
        import numpy as np
        from backend.app.ai_pipeline.retrieval import vector
        for value in ([1]*512,[0]*384,[float('nan')]*1024):
            with self.assertRaises(ValueError):vector(value)
        self.assertEqual(vector(np.ones(1024)/32).shape,(1024,))

    def test_local_embedding_failure_is_actionable_and_model_change_is_rejected(self):
        from backend.app.ai_pipeline.embeddings import OllamaEmbedding
        tags=httpx.Response(200,json={'models':[{'name':'bge-m3:latest','digest':'abc'}]},request=httpx.Request('GET','http://localhost'))
        with patch.dict(os.environ,{'OLLAMA_URL':'http://127.0.0.1:11434','OLLAMA_EMBED_MODEL':'bge-m3:latest'}),patch('httpx.Client.get',return_value=tags):
            enc=OllamaEmbedding()
            with patch('httpx.Client.post',side_effect=httpx.ReadTimeout('local timeout')):
                with self.assertRaises(ValueError):enc.encode(['질문'])
            enc.digest='changed'
            with patch('httpx.Client.post') as call:
                with self.assertRaises(ValueError):enc.encode(['질문'])
                call.assert_not_called()
