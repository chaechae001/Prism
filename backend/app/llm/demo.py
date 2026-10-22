"""고정된 가상 응답으로 요약 처리 흐름을 확인합니다. 실제 LLM 호출은 없습니다."""

import argparse
import json
from pathlib import Path

from .schemas import ArticleBody
from .summarizer import summarize_article


def sample_article() -> ArticleBody:
    return ArticleBody(
        id="article-llm-demo-001", title="[가상] 지역 도서관 주말 운영 확대",
        text=("가상시립도서관은 다음 달부터 토요일 운영 시간을 오후 6시에서 오후 8시로 "
              "늘린다고 밝혔다. 시범 운영 기간은 3개월이다. 도서관은 이용 현황을 확인한 뒤 "
              "운영 연장 여부를 결정할 예정이다. 추가 예산 규모는 이번 발표에 포함되지 않았다."),
        is_demo=True,
    )


def _fixed_demo_response(system_prompt: str, user_prompt: str) -> str:
    # 테스트 기사의 정해진 답을 직접 작성한 것입니다. LLM이 생성한 결과가 아닙니다.
    article = json.loads(user_prompt)
    return json.dumps({
        "title": "[가상] 도서관 토요일 운영 시간 시범 확대",
        "bullets": [
            {"text": "가상시립도서관은 다음 달부터 토요일 운영 시간을 오후 8시까지 늘린다.",
             "article_ids": [article["id"]]},
            {"text": "시범 운영은 3개월이며 이용 현황을 확인한 뒤 연장 여부를 결정한다.",
             "article_ids": [article["id"]]},
        ],
        "perspectives": [],
        "unknowns": ["추가 예산 규모는 발표에 포함되지 않았다."],
    }, ensure_ascii=False)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, default=Path("work/llm_demo_result.json"))
    args = cli.parse_args()
    result = summarize_article(
        sample_article(), generate=_fixed_demo_response, model_version="test-only-fixed-response",
        is_mock=True,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print("실제 LLM 호출: 없음 (고정된 가상 응답)")
    print(f"입력 기사: {result.article_id}")
    print(f"요약 항목: {len(result.summary.bullets)}개")
    print("상태: pending / is_mock: true / is_demo: true")
    print(f"결과 파일: {args.output.resolve()}")


if __name__ == "__main__":
    main()
