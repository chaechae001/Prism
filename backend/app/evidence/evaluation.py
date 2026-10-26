"""Deterministic regression and metadata evaluation, never invented human scores."""
from collections import Counter
from math import ceil,isfinite
from ..services.reading_modes import materialize,checked

def evaluate_suite(suite):
    if suite.get('schema_version')!='prism-reading-regression/v1' or suite.get('provenance')!='synthetic':
        raise ValueError('명시적인 합성 회귀 형식이 필요합니다.')
    cases=suite.get('cases')
    if not isinstance(cases,list) or not cases:raise ValueError('평가 사례가 필요합니다.')
    seen=set();rows=[];totals=Counter(tp=0,fp=0,fn=0)
    for case in cases:
        identity=case['id']
        if not isinstance(identity,str) or identity in seen:raise ValueError('평가 ID가 중복되었거나 잘못되었습니다.')
        seen.add(identity)
        expected=case['expected_labels']
        if len(expected)!=len(set(expected)):raise ValueError('예상 항목이 중복되었습니다.')
        output=checked(materialize(case['draft'],case['catalog'],'five_w'),case['bodies'],'five_w')
        actual=[item.label for item in output.items]
        tp=len(set(actual)&set(expected));fp=len(set(actual)-set(expected));fn=len(set(expected)-set(actual))
        totals.update(tp=tp,fp=fp,fn=fn)
        rows.append({'id':identity,'expected_labels':expected,'actual_labels':actual,'passed':actual==expected})
    tp,fp,fn=(totals[k] for k in ('tp','fp','fn'))
    return {'scope':'synthetic_structural_and_role_guard_regression','real_world_accuracy_measured':False,
        'case_count':len(rows),'passed_cases':sum(row['passed'] for row in rows),**totals,
        'label_precision':tp/(tp+fp) if tp+fp else None,'label_recall':tp/(tp+fn) if tp+fn else None,
        'cases':rows,'notice':'정해진 합성 응답을 검사한 회귀 결과입니다. 모델의 의미 판단·실기사 정확도·인젝션 방어율·사용자 효과를 측정한 결과가 아닙니다.'}

def percentile(values,q):
    if not values:return None
    return sorted(values)[max(0,ceil(q*len(values))-1)]

def operation_summary(records):
    if not isinstance(records,list):raise ValueError('호출 기록 목록이 필요합니다.')
    all_latency=[];success_latency=[];costs=[];errors=0
    for row in records:
        elapsed=row.get('elapsed_ms');cost=row.get('estimated_cost_usd')
        if row.get('status') not in {'ok','error'} or type(elapsed) not in {int,float} or not isfinite(elapsed) or elapsed<0:
            raise ValueError('호출 상태와 지연을 확인해주세요.')
        if cost is not None:
            if type(cost) not in {int,float} or not isfinite(cost) or cost<0:raise ValueError('비용을 확인해주세요.')
            costs.append(cost)
        all_latency.append(elapsed)
        if row['status']=='ok':success_latency.append(elapsed)
        else:errors+=1
    n=len(records)
    return {'calls':n,'errors':errors,'error_rate':errors/n if n else None,
        'latency_ms':{'all':{'p50':percentile(all_latency,.5),'p95':percentile(all_latency,.95)},
            'success':{'p50':percentile(success_latency,.5),'p95':percentile(success_latency,.95)}},
        'cost_known_calls':len(costs),'cost_coverage':len(costs)/n if n else None,
        'known_estimated_cost_usd':sum(costs) if costs else None,
        'notice':'입력 표본 범위의 nearest-rank 분위수입니다. 비용 미상은 0원이 아니며 실제 청구 금액이 아닙니다.'}
