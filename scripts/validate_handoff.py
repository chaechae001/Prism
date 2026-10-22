import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.models import AnalystBatch
from app.pipeline import allowed_articles
path=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'contracts/analyst-batch.example.json'
batch=AnalystBatch.model_validate_json(path.read_text(encoding='utf-8'))
allowed=allowed_articles(batch)
print(f'{batch.batch_id}: {len(batch.articles)} input, {len(allowed)} rights-eligible and deduplicated articles')
print('Structure validation only. Collection, clustering, summary generation and publication have not run.')
