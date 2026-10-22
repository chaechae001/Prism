"""Golden response semantics for frontend MSW/FastAPI parity tests. No live server needed."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)
cases=[]
for mode in ['balanced','latest','explore']:
    for diversity in [0,70,100]:
        for category in ['', 'politics', 'technology']:
            params={'mode':mode,'diversity':diversity,'limit':4}
            if category:params['category']=category
            r=client.get('/api/v1/stories',params=params).json()
            cases.append({'query':params,'ids':[i['story']['id'] for i in r['items']],
                'reasons':[i['reason']['code'] for i in r['items']],'total':r['total'],'cursor':r['next_cursor']})
cases.append({'query':{'q':' AI ','limit':1},'ids':['story-001'],'reasons':['source_diversity'],'total':1,'cursor':None})
(ROOT/'contracts/parity-cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Exported {len(cases)} parity cases')
