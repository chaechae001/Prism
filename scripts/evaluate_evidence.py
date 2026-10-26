"""Offline-only evidence evaluation. No model calls, downloads, or DB writes."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.app.evidence.evaluation import evaluate_suite,operation_summary

def main():
    parser=argparse.ArgumentParser(description='합성 회귀·기존 호출 메타데이터 평가 (외부 호출 없음)')
    parser.add_argument('--suite',type=Path)
    parser.add_argument('--operations',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--fail-on-regression',action='store_true')
    args=parser.parse_args()
    if bool(args.suite)==bool(args.operations):parser.error('--suite 또는 --operations 중 하나만 선택해주세요.')
    try:
        value=json.loads((args.suite or args.operations).read_text(encoding='utf-8-sig'))
        result=evaluate_suite(value) if args.suite else operation_summary(value)
        text=json.dumps(result,ensure_ascii=False,indent=2)
        if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text+'\n',encoding='utf-8')
        print(text)
        return int(bool(args.fail_on_regression and args.suite and result['passed_cases']!=result['case_count']))
    except (ValueError,TypeError,KeyError,OSError):
        print(json.dumps({'success':False,'notice':'입력 형식·파일·평가 스키마를 확인해주세요. 원문·비밀값은 출력하지 않습니다.'},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
