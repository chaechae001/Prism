"""Run after editing Pydantic models, then run npm run types:api in frontend."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.main import app
from app.models import AnalystBatch, SummaryOutput
for name,value in [('openapi',app.openapi()),('analyst-batch.schema',AnalystBatch.model_json_schema()),('summary-output.schema',SummaryOutput.model_json_schema())]:
    (ROOT/'contracts'/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Exported OpenAPI and analyst/summary JSON schemas')
