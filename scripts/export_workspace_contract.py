"""Export additive account/editorial endpoints without altering news v1 contracts."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.api import app

schema=app.openapi()
schema['paths']={k:v for k,v in schema['paths'].items() if k.startswith(('/api/account/','/api/editorial/','/api/local/'))}
(ROOT/'contracts/workspace-openapi.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('계정·편집 API 계약을 내보냈습니다. 기존 뉴스 v1 계약은 유지합니다.')
