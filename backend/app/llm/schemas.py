"""기존 RSS JSON과 별도로 사용하는 기사 한 건 요약용 내부 형식."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Sentence = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ArticleBody(StrictModel):
    id: Identifier
    title: Title
    # RSS description 대신 실제 입력으로 받은 본문을 명시합니다.
    # 초기 제한은 문자 수 기준이며 선택할 모델의 토큰 한도와는 별개입니다.
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30000)]
    is_demo: bool = False


class SummaryBullet(StrictModel):
    text: Sentence
    article_ids: Annotated[list[Identifier], Field(min_length=1, max_length=1)]


class Perspective(StrictModel):
    label: Sentence
    text: Sentence
    article_ids: Annotated[list[Identifier], Field(min_length=1)]


class SummaryDraft(StrictModel):
    # 기존 DATA_HANDOFF.md의 요약 결과 키를 참고하되 이번 구현은 기사 한 건의 초안입니다.
    title: Title
    bullets: Annotated[list[SummaryBullet], Field(min_length=1, max_length=3)]
    # 기사 한 건에서 여러 출처의 관점을 만든 것처럼 표시하지 않습니다.
    perspectives: Annotated[list[Perspective], Field(max_length=0)]
    unknowns: Annotated[list[Sentence], Field(max_length=5)]


class SummaryResult(StrictModel):
    article_id: Identifier
    summary: SummaryDraft
    # 생성 성공과 공개 승인은 구분합니다. 검토 전 초안이므로 pending을 유지합니다.
    status: Literal["pending"] = "pending"
    model_version: Identifier
    prompt_version: Identifier
    is_mock: bool
    is_demo: bool
