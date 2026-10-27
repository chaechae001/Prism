"""Offline reviewed evaluation. No network, model, DB or automatic human labels."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.evidence.benchmark import evaluate, template
from backend.app.evidence.security_packet import prepare_packet


def main():
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--input', type=Path)
    g.add_argument('--template', action='store_true')
    g.add_argument('--security-packet', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        result = template() if args.template else prepare_packet() if args.security_packet else evaluate(json.loads(args.input.read_text(encoding='utf-8-sig')))
        if args.output.exists():
            raise ValueError('기존 파일은 덮어쓰지 않습니다.')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'saved': True, 'input_cases': result.get('input_cases'),
                          'paired_cases': result.get('paired_cases'),
                          'real_world_accuracy_measured': result.get('real_world_accuracy_measured', False)}))
        return 0
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({'saved': False, 'notice': '스키마·검토·분리·출력 경로를 확인해주세요. 원문은 로그에 출력하지 않습니다.'}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
