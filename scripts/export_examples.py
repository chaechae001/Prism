"""Export full, valid examples from the running ASGI implementation (no LLM/DB)."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)
examples={
  'categories.response': client.get('/api/v1/categories').json(),
  'list.response': client.get('/api/v1/stories?limit=1').json(),
  'search.response': client.get('/api/v1/stories?q=AI&category=technology').json(),
  'story.response': client.get('/api/v1/stories/story-001').json(),
  'pending-story.response': client.get('/api/v1/stories/story-009').json(),
  'feedback.request': {'story_id':'story-001','kind':'more_perspectives','comment':'다른 관점도 궁금해요.'},
  'validation-error.response': client.get('/api/v1/stories?diversity=101').json(),
  'job.request': {'stage':'summarize','dry_run':True},
}
examples['feedback.response']=client.post('/api/v1/feedback',json=examples['feedback.request']).json()
folder=ROOT/'contracts/examples';folder.mkdir(exist_ok=True)
for name,value in examples.items():
    (folder/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Exported {len(examples)} complete JSON request/response examples')
