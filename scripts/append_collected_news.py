"""Explicit local-test article append. No collection or model call in this CLI."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.services.supplemental_news import append,prepare,snapshot
p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--namespace',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
try:
 raw=json.loads(Path(a.input).read_text(encoding='utf-8'));rows=raw['articles'] if isinstance(raw,dict) else raw
 if a.apply:result=append(a.namespace,rows)
 else:
  _,payload=snapshot(a.namespace);bundle,added=prepare(payload,rows)
  result={'added':len(added),'total_articles':len(bundle['payload']['articles']),'database_writes':0}
 print(json.dumps(result,ensure_ascii=False))
except Exception as e:
 print(json.dumps({'error_type':type(e).__name__,'notice':'입력·현재 배치·DB 연결을 확인해주세요.'},ensure_ascii=False));raise SystemExit(1)
