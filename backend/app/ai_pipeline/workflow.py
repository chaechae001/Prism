"""Durable local LangGraph review workflow. Checkpoints contain IDs, not source text."""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import TypedDict
from uuid import UUID,uuid4

from ..config import ROOT
from ..reader_accounts import story_for
from ..services import editorial


class State(TypedDict,total=False):
    story_id:str
    input_hash:str
    draft_id:str
    phase:str
    approved:bool


def location():
    path=Path(os.getenv('PRISM_WORKFLOW_DB',str(ROOT/'data/private/ai/workflows.sqlite'))).resolve()
    if not any(path.is_relative_to(base) for base in (ROOT/'data/private',ROOT/'.local-archive')): raise ValueError('프로젝트의 data/private 또는 .local-archive 폴더를 사용해주세요.')
    path.parent.mkdir(parents=True,exist_ok=True)
    return path


def graph(checkpointer,*,generate=None,validate=None,publish=None):
    from langgraph.graph import StateGraph,START,END
    from langgraph.types import interrupt,RetryPolicy
    async def check(state):
        value=await asyncio.to_thread(validate or editorial.source_state,state['story_id'])
        return {'input_hash':value['hash'],'phase':'validated'}
    async def create(state):
        active=await asyncio.to_thread(validate or editorial.source_state,state['story_id'])
        if active['hash']!=state['input_hash']:raise ValueError('검증 후 원문 버전이 바뀌었습니다.')
        if generate is not None:value=await generate(state)
        else:
            story=await asyncio.to_thread(story_for,state['story_id'])
            value=await editorial.generate(story)
        return {'draft_id':value['id'],'phase':'awaiting_review'}
    def wait(state):
        decision=interrupt({'draft_id':state['draft_id'],'stage':'review_required'})
        if type(decision) is not bool:raise ValueError('승인 여부를 true/false로 지정해주세요.')
        return {'approved':decision}
    async def apply(state):
        # editorial.review revalidates the current sources and publication rights.
        await asyncio.to_thread(publish or editorial.review,state['draft_id'],state['approved'])
        return {'phase':'published' if state['approved'] else 'rejected'}
    builder=StateGraph(State)
    builder.add_node('validate_sources',check,retry_policy=RetryPolicy(max_attempts=2,retry_on=(ConnectionError,TimeoutError)))
    builder.add_node('generate_draft',create)
    builder.add_node('human_review',wait)
    builder.add_node('publish_or_hold',apply)
    builder.add_edge(START,'validate_sources');builder.add_edge('validate_sources','generate_draft')
    builder.add_edge('generate_draft','human_review');builder.add_edge('human_review','publish_or_hold');builder.add_edge('publish_or_hold',END)
    return builder.compile(checkpointer=checkpointer)


@asynccontextmanager
async def runtime():
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langsmith import tracing_context
    async with AsyncSqliteSaver.from_conn_string(str(location())) as saver:
        saver.serde=JsonPlusSerializer(pickle_fallback=False)
        with tracing_context(enabled=False):yield graph(saver)


def config(identity):return {'configurable':{'thread_id':str(UUID(identity))},'callbacks':[]}


def result(identity,state):
    return {'workflow_id':identity,'id':state.get('draft_id'),'phase':state.get('phase','pending'),'story_id':state.get('story_id')}


async def start(story_id):
    identity=str(uuid4())
    async with runtime() as app:
        try:state=await app.ainvoke({'story_id':story_id,'phase':'pending'},config(identity))
        except Exception:
            saved=await app.aget_state(config(identity))
            state={**saved.values,'phase':'failed'}
    return result(identity,state)


async def inspect(identity):
    async with runtime() as app:
        snapshot=await app.aget_state(config(identity))
    if not snapshot.values:raise ValueError('작업 상태를 찾을 수 없습니다.')
    value=result(identity,snapshot.values)
    if any(task.error for task in snapshot.tasks):value['phase']='failed'
    return value


async def resume(identity,approve):
    from langgraph.types import Command
    async with runtime() as app:
        before=await app.aget_state(config(identity))
        if before.values.get('phase')!='awaiting_review' or not before.next:raise ValueError('검토 대기 상태가 아닙니다.')
        state=await app.ainvoke(Command(resume=approve),config(identity))
    return result(identity,state)


async def retry(identity):
    async with runtime() as app:
        before=await app.aget_state(config(identity))
        if not before.next or not any(task.error for task in before.tasks):raise ValueError('재시도할 실패 작업이 없습니다.')
        try:state=await app.ainvoke(None,config(identity))
        except Exception:
            saved=await app.aget_state(config(identity));state={**saved.values,'phase':'failed'}
    return result(identity,state)
