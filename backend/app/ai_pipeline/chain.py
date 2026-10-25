"""LangChain runnables around the existing provider and strict Pydantic parser."""
import json


async def context(story,question,resolver):
    from langchain_core.runnables import RunnableLambda
    from langsmith import tracing_context
    retriever=RunnableLambda(lambda value:resolver(value['story'],value['question']),name='selected_event_retriever')
    with tracing_context(enabled=False):
        return await retriever.ainvoke({'story':story,'question':question},config={'callbacks':[]})


async def invoke(payload,provider,output_type):
    from langchain_core.runnables import RunnableLambda
    from langchain_core.output_parsers import PydanticOutputParser
    from langsmith import tracing_context
    async def model_step(value):
        result=await provider(value)
        return result.model_dump_json() if hasattr(result,'model_dump_json') else json.dumps(result,ensure_ascii=False)
    chain=RunnableLambda(model_step,name='selected_news_model')|PydanticOutputParser(pydantic_object=output_type)
    # Explicitly disable ambient LangSmith tracing; only redacted Opik is opt-in.
    with tracing_context(enabled=False):
        return await chain.ainvoke(payload,config={'callbacks':[],'run_name':'prism_structured_news'})
