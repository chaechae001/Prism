"""연결 확인 또는 가상 기사 한 건의 실제 엘리스 요약 실행."""

import argparse
import json
from pathlib import Path

from .elice_client import EliceClient
from .elice_settings import EliceSettings
from .schemas import ArticleBody
from .summarizer import LLMSummaryError, summarize_article


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="생성 없이 모델 목록과 인증 상태 확인")
    summary = commands.add_parser("summarize", help="실제 모델 호출 1회; 사용량/크레딧 차감 가능")
    summary.add_argument("--input", type=Path, required=True)
    summary.add_argument("--output", type=Path, default=Path("work/llm_elice_result.json"))
    summary.add_argument("--diagnostic", action="store_true", help="400 오류의 키·입력을 가린 상세 문구 표시")
    args = parser.parse_args()
    client = None
    try:
        settings = EliceSettings.from_env()
        article = None
        if args.command == "summarize":
            if args.input.stat().st_size > 200000 or args.input.resolve() == args.output.resolve():
                raise ValueError("입력 크기 또는 출력 경로를 확인하세요.")
            article = ArticleBody.model_validate_json(args.input.read_text(encoding="utf-8-sig"))
        client = EliceClient(settings)
        if args.command == "check":
            client.check()
            print("엘리스 연결·인증·모델 목록: 정상")
            print("요약 생성 요청: 없음")
            return
        result = summarize_article(article, generate=client.generate,
                                   model_version=settings.model, is_mock=False)
        result = result.model_copy(update={"model_version": client.last_model})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print("엘리스 요약 호출: 완료 (사용량/크레딧 차감 가능)")
        print(f"상태: pending / is_mock: false / is_demo: {str(result.is_demo).lower()}")
        print(f"응답 모델: {result.model_version}")
        print("토큰 사용량: " + json.dumps(client.last_usage, ensure_ascii=False))
        print(f"결과 파일: {args.output.resolve()}")
    except LLMSummaryError as exc:
        print(f"실패 [{exc.code}]: {exc}")
        if args.command == "summarize" and args.diagnostic and client is not None and client.last_error_detail:
            print("마스킹한 서버 설명: " + client.last_error_detail)
        print("자동 재시도하지 않았습니다. 기존 결과 파일이 있다면 이전 실행 결과입니다.")
        raise SystemExit(1) from None
    except (OSError, ValueError):
        print("실패 [INPUT_OR_CONFIG_ERROR]: 입력 파일·JSON·ELICE_* 설정을 확인하세요.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
