"""Explicit worker commands. Reads/checks by default; run/once require --apply."""
import argparse
import json
import signal
from threading import Event

from .settings import load_settings


def main(argv=None):
    parser=argparse.ArgumentParser(description='Local-test RSS → DB → clustering worker. No LLM.')
    parser.add_argument('command',choices=('check','schema','once','run'))
    parser.add_argument('--config',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    try:
        settings=load_settings(args.config)
        if args.command=='schema':
            from .repository import install_schema,schema_status
            value=install_schema() if args.apply else schema_status()
        elif args.command=='check' or not args.apply:
            value=dict(**settings.check(),status='plan_only')
        elif args.command=='once':
            from .runner import run_cycle
            value=run_cycle(settings)
        else:
            from .runner import run_forever
            stop=Event()
            def end(*_):stop.set()
            for name in ('SIGINT','SIGTERM'):
                if hasattr(signal,name):signal.signal(getattr(signal,name),end)
            run_forever(settings,stop=stop,emit=lambda value:print(json.dumps(value,ensure_ascii=False),flush=True))
            return 0
        print(json.dumps(value,ensure_ascii=False));return 0
    except Exception as exc:
        print(json.dumps(dict(status='failed',error_type=type(exc).__name__,
            message='설정·연결·로컬 모델 또는 출처 수집 상태를 확인해주세요. 원문과 접속 정보는 출력하지 않습니다.'),ensure_ascii=False))
        return 1


if __name__=='__main__':raise SystemExit(main())
