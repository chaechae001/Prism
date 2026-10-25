"""Human-reviewed, explicitly permitted fine-tuning data preparation. No training calls."""
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path


def prepare(records):
    if not isinstance(records,list) or not 1<=len(records)<=10000:raise ValueError('검토된 정답 사례 1~10,000개가 필요합니다.')
    groups=defaultdict(list);seen=set();bodies={}
    for r in records:
        if not isinstance(r,dict) or set(r)-{'id','event_group','input','answer','human_reviewed','approved_for_training','is_demo'}:raise ValueError('허용되지 않은 학습 사례 필드입니다.')
        if 'is_demo' in r and type(r['is_demo']) is not bool:raise ValueError('가상 자료 표시는 true/false여야 합니다.')
        if not isinstance(r,dict) or r.get('human_reviewed') is not True or r.get('approved_for_training') is not True:
            raise ValueError('모든 사례에 사람 검토와 학습 이용 허용이 필요합니다.')
        for key in ('id','event_group','input','answer'):
            if not isinstance(r.get(key),str) or not r[key].strip():raise ValueError('사례 ID·사건 그룹·입력·정답이 필요합니다.')
            if len(r[key])>(100000 if key in {'input','answer'} else 200):raise ValueError('학습 사례 필드 길이를 초과했습니다.')
        if r['id'] in seen:raise ValueError('중복 사례 ID입니다.')
        seen.add(r['id']);digest=sha256(r['input'].encode()).hexdigest()
        if digest in bodies and bodies[digest]!=r['event_group']:raise ValueError('동일 입력을 서로 다른 사건 그룹에 배치할 수 없습니다.')
        bodies[digest]=r['event_group'];groups[r['event_group']].append(r)
    if len(groups)<3:raise ValueError('사건 단위 분리를 위해 서로 다른 사건 그룹이 3개 이상 필요합니다.')
    ordered=sorted(groups,key=lambda s:sha256(s.encode()).hexdigest())
    n=len(ordered);n_test=max(1,round(n*.1));n_val=max(1,round(n*.1))
    partitions={'test':ordered[:n_test],'validation':ordered[n_test:n_test+n_val],'train':ordered[n_test+n_val:]}
    output={}
    for split,ids in partitions.items():
        output[split]=[{'messages':[{'role':'system','content':'제공된 뉴스 근거만 사용해 한국어로 답하고 모르는 사실은 추측하지 마세요.'},
            {'role':'user','content':r['input']},{'role':'assistant','content':r['answer']}]} for identity in ids for r in groups[identity]]
    manifest={'schema_version':'prism-reviewed-training/v1','counts':{k:len(v) for k,v in output.items()},
        'groups':partitions,'training_started':False,'notice':'학습과 평가는 별도 실행입니다. 이 명령은 외부 모델·학습 서비스에 자료를 전송하지 않습니다.'}
    return output,manifest


def export(source,target):
    target=Path(target).resolve()
    from ..config import ROOT
    if not any(target.is_relative_to(base) for base in (ROOT/'data/private',ROOT/'.local-archive')):raise ValueError('학습 파일은 프로젝트의 data/private 또는 .local-archive 폴더에 저장해주세요.')
    value=json.loads(Path(source).read_text(encoding='utf-8-sig'));output,manifest=prepare(value)
    if target.exists() and any(target.iterdir()):raise ValueError('빈 출력 폴더를 사용해주세요.')
    target.mkdir(parents=True,exist_ok=True)
    for key,rows in output.items():(target/(key+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


def evaluate(cases):
    if not isinstance(cases,list) or not cases:raise ValueError('평가 사례가 필요합니다.')
    rows=[]
    for c in cases:
        expected=c.get('expected_facts',[]);forbidden=c.get('forbidden_facts',[]);answer=c.get('answer','');cited=c.get('article_ids',[]);allowed=c.get('allowed_article_ids',[])
        if not isinstance(answer,str) or not all(isinstance(v,list) and all(isinstance(s,str) for s in v) for v in (expected,forbidden,cited,allowed)):
            raise ValueError('평가 입력 형식을 확인해주세요.')
        rows.append({'id':c.get('id'),'citations_valid':bool(cited) and set(cited).issubset(allowed),
            'expected_fact_hits':sum(f in answer for f in expected),'expected_fact_count':len(expected),
            'forbidden_fact_hits':sum(f in answer for f in forbidden)})
    return {'cases':rows,'notice':'문자열 기준 회귀 검사입니다. 사실성·객관성의 전체 정확도나 사람 평가를 대체하지 않습니다.'}
