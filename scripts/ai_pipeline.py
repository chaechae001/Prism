"""Explicit AI storage/dataset commands. No automatic training or model download."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description='AI 검색·운영 스키마와 검토된 학습 자료 준비')
    sub=parser.add_subparsers(dest='command',required=True)
    s=sub.add_parser('schema');s.add_argument('--apply',action='store_true')
    d=sub.add_parser('prepare-training');d.add_argument('--input',required=True);d.add_argument('--output',required=True)
    e=sub.add_parser('evaluate');e.add_argument('--input',required=True)
    args=parser.parse_args()
    try:
        if args.command=='schema':
            from backend.app.ai_pipeline.schema import install,status
            result=install() if args.apply else status()
        elif args.command=='prepare-training':
            from backend.app.ai_pipeline.datasets import export
            result=export(args.input,args.output)
        else:
            from backend.app.ai_pipeline.datasets import evaluate
            result=evaluate(json.loads(Path(args.input).read_text(encoding='utf-8-sig')))
        print(json.dumps(result,ensure_ascii=False,default=str));return 0
    except Exception as exc:
        print(json.dumps({'success':False,'error_type':type(exc).__name__,'notice':'입력 형식·허용 상태·설정을 확인해주세요. 비밀값·원문·외부 오류 전문은 출력하지 않습니다.'},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
