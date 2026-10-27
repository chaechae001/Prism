"""Offline, paired evaluation of reviewed evidence; never calls a model.

Reviewer identifiers are self-declared provenance, not proof of human review.
No answer text is copied to the report. Unreviewed judgments stay out of scores.
"""
from collections import Counter
from hashlib import sha256
from math import isfinite
import re
from .evaluation import operation_summary

VERSION = 'prism-reviewed-evaluation/v1'


def identity(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError('ID 또는 버전 정보를 확인해주세요.')
    return value


def unique(values):
    if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError('ID 목록을 확인해주세요.')
    if len(values) != len(set(values)):
        raise ValueError('중복 ID입니다.')
    return values


def reviewed(value):
    if not isinstance(value, dict):
        raise ValueError('검토 메타데이터가 필요합니다.')
    people = unique(value.get('reviewer_ids', []))
    if type(value.get('adjudicated')) is not bool:
        raise ValueError('불일치 조정 여부가 필요합니다.')
    return len(people) >= 2 and value['adjudicated']


def ratio(a, b):
    return a / b if b else None


def template():
    return {'schema_version': VERSION, 'provenance': 'human',
            'protocol': {'dataset_version': 'pending-v1', 'output_token_limit': 1800,
                         'prompt_template_id': 'pending-v1', 'top_k': 6},
            'variants': [{'id': 'commercial-direct', 'provider': 'elice', 'context_mode': 'direct'},
                         {'id': 'commercial-rag', 'provider': 'elice', 'context_mode': 'rag'},
                         {'id': 'local-direct', 'provider': 'ollama', 'context_mode': 'direct'},
                         {'id': 'local-rag', 'provider': 'ollama', 'context_mode': 'rag'}],
            'cases': [],
            'instructions': '사건별 split·입력 해시·2인 정답 검토를 먼저 작성하세요. '
                            '예측과 판정을 실제 수행 전 채우지 마세요. 외부 호출은 이 도구에서 실행하지 않습니다.'}


def evaluate(data):
    if data.get('schema_version') != VERSION or data.get('provenance') not in {'human', 'synthetic'}:
        raise ValueError('평가 버전과 자료 출처가 필요합니다.')
    protocol = data['protocol']
    for key in ('dataset_version', 'prompt_template_id'):
        identity(protocol[key])
    if type(protocol['output_token_limit']) is not int or not 1 <= protocol['output_token_limit'] <= 2000:
        raise ValueError('동일한 출력 토큰 한도가 필요합니다.')
    k = protocol['top_k']
    if type(k) is not int or not 1 <= k <= 12:
        raise ValueError('검색 k 범위는 1~12입니다.')
    variants = data['variants']
    if not isinstance(variants, list) or len(variants) < 2:
        raise ValueError('비교할 실행 조건이 2개 이상 필요합니다.')
    names = unique([identity(v['id']) for v in variants])
    configurations = {v['id']: v for v in variants}
    for variant in variants:
        identity(variant['provider'])
        if variant['context_mode'] not in {'direct', 'rag'}:
            raise ValueError('문맥 방식은 direct/rag여야 합니다.')
    cases = data['cases']
    if not isinstance(cases, list) or len(cases) > 10000:
        raise ValueError('평가 사례는 최대 10,000개입니다.')
    ids = set(); events = {}; hashes = {}; all_rows = {}; paired = []
    excluded = Counter(); attempts = {name: [] for name in names}; versions = {}
    for case in cases:
        cid = identity(case['id']); event = identity(case['event_id'])
        if cid in ids:
            raise ValueError('중복 평가 사례입니다.')
        ids.add(cid)
        split = case['split']
        if split not in {'development', 'test'}:
            raise ValueError('개발/최종 평가 분리가 필요합니다.')
        digest = case['input_sha256']
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('실제 입력 SHA-256이 필요합니다.')
        if 'input' in case and (not isinstance(case['input'], str) or sha256(case['input'].encode()).hexdigest() != digest):
            raise ValueError('입력 본문과 버전 해시가 다릅니다.')
        if event in events and events[event] != split or digest in hashes and hashes[digest] != split:
            raise ValueError('동일 사건 또는 입력이 개발/최종 평가에 섞였습니다.')
        events[event] = split; hashes[digest] = split
        gold = case['expected']
        allowed = unique(gold['allowed_article_ids']); relevant = unique(gold['relevant_chunk_ids'])
        if type(gold['answerable']) is not bool:
            raise ValueError('정답 가능 여부를 확인해주세요.')
        if not gold['answerable'] and relevant:
            raise ValueError('근거 없는 질문에 정답 청크를 지정할 수 없습니다.')
        gold_ready = reviewed(case['review'])
        predictions = case['predictions']
        if not isinstance(predictions, list):
            raise ValueError('실행 결과 목록이 필요합니다.')
        observed = set(); valid = {}
        for pred in predictions:
            name = pred['variant']
            if name not in names or name in observed:
                raise ValueError('실행 조건이 없거나 중복됐습니다.')
            observed.add(name)
            if pred['input_sha256'] != digest or pred['output_token_limit'] != protocol['output_token_limit'] or pred['prompt_template_id'] != protocol['prompt_template_id']:
                raise ValueError('같은 입력·프롬프트·출력 한도로 비교해야 합니다.')
            identity(pred['model']); identity(pred['prompt_version'])
            version = (pred['model'], pred['prompt_version'])
            if name in versions and versions[name] != version:
                raise ValueError('실행 조건 안에서 모델·프롬프트 버전을 섞을 수 없습니다.')
            versions[name] = version
            if type(pred['external_processing']) is not bool or type(pred['abstained']) is not bool:
                raise ValueError('전송 경로와 답변 보류를 기록해주세요.')
            provider = configurations[name]['provider']
            if provider == 'ollama' and pred['external_processing'] or provider == 'elice' and not pred['external_processing']:
                raise ValueError('실행 조건과 실제 외부 전송 여부가 다릅니다.')
            chunks = unique(pred['retrieved_chunk_ids']); cited = unique(pred['cited_article_ids'])
            operation_summary([pred])  # validates finite latency, status and nullable cost
            attempts[name].append(pred)
            if pred['status'] == 'error':
                excluded['failed_execution'] += 1
                continue
            if not gold_ready:
                excluded['unreviewed_gold'] += 1
                continue
            judgment = pred.get('judgment')
            if judgment is None or not reviewed(judgment):
                excluded['unreviewed_prediction'] += 1
                continue
            for num, den in [('supported_claims', 'total_claims'), ('correct_citations', 'total_citations')]:
                if any(type(judgment.get(v)) is not int or judgment[v] < 0 for v in (num, den)) or judgment[num] > judgment[den]:
                    raise ValueError('사람 판정의 분자·분모를 확인해주세요.')
            for key in ('task_success', 'attack_succeeded'):
                if judgment.get(key) is not None and type(judgment[key]) is not bool:
                    raise ValueError('미판정은 null로 남겨주세요.')
            kind = case.get('kind', 'clean')
            if kind not in {'clean', 'injection'}:
                raise ValueError('일반/공격 표본 유형이 필요합니다.')
            valid[name] = {'case_id': cid, 'split': split, 'kind': kind,
                'recall_at_k': ratio(len(set(chunks[:k]) & set(relevant)), len(relevant)),
                'citation_membership_valid': bool(cited) and set(cited).issubset(allowed),
                'abstention_correct': pred['abstained'] == (not gold['answerable']),
                'judgment': judgment, 'operation': pred}
        all_rows[cid] = valid
        if set(valid) == set(names):
            paired.append(cid)
        else:
            excluded['incomplete_paired_case'] += 1
    reports = {}
    for split in ('development', 'test'):
        reports[split] = {}
        for name in names:
            rows = [all_rows[cid][name] for cid in paired if all_rows[cid][name]['split'] == split]
            j = [r['judgment'] for r in rows]
            recall = [r['recall_at_k'] for r in rows if r['recall_at_k'] is not None]
            attacks = [r['judgment']['attack_succeeded'] for r in rows if r['kind'] == 'injection' and r['judgment'].get('attack_succeeded') is not None]
            clean = [r['judgment']['task_success'] for r in rows if r['kind'] == 'clean' and r['judgment'].get('task_success') is not None]
            reports[split][name] = {'paired_cases': len(rows), 'retrieval_labeled_cases': len(recall),
                'mean_recall_at_k': ratio(sum(recall), len(recall)),
                'claim_support_rate': ratio(sum(v['supported_claims'] for v in j), sum(v['total_claims'] for v in j)),
                'citation_correct_rate': ratio(sum(v['correct_citations'] for v in j), sum(v['total_citations'] for v in j)),
                'citation_membership_valid_rate': ratio(sum(r['citation_membership_valid'] for r in rows), len(rows)),
                'abstention_correct_rate': ratio(sum(r['abstention_correct'] for r in rows), len(rows)),
                'attack_judged_cases': len(attacks), 'attack_success_rate': ratio(sum(attacks), len(attacks)),
                'clean_judged_cases': len(clean), 'clean_task_success_rate': ratio(sum(clean), len(clean)),
                'operations': operation_summary([r['operation'] for r in rows])}
    return {'schema_version': VERSION, 'provenance': data['provenance'],
            'protocol': {key: protocol[key] for key in ('dataset_version', 'output_token_limit', 'prompt_template_id', 'top_k')},
            'variants': [{'id': name, 'provider': configurations[name]['provider'],
                          'context_mode': configurations[name]['context_mode'],
                          'model': versions.get(name, (None, None))[0],
                          'prompt_version': versions.get(name, (None, None))[1]} for name in names],
            'input_cases': len(cases), 'paired_cases': len(paired), 'excluded': dict(excluded),
            'results': reports, 'all_attempt_operations': {name: operation_summary(rows) for name, rows in attempts.items()},
            'real_world_accuracy_measured': data['provenance'] == 'human' and any(all_rows[cid][names[0]]['split'] == 'test' for cid in paired),
            'notice': '입력된 검토 기록의 집계입니다. 검토자 진위는 자체 증명하지 않습니다. '
                      '개발/최종·합성/실제·미판정/오류를 구분합니다. 완전한 짝 표본만 품질 비교에 사용하며 제외 수를 함께 확인하세요. '
                      '원문·질문·답변·키는 보고서에 복사하지 않습니다.'}
