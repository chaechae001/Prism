"""모델 호출 함수를 주입받아 기사 한 건의 요약 초안을 처리합니다."""

from collections.abc import Callable

from pydantic import ValidationError

from .prompts import PROMPT_VERSION, build_messages
from .schemas import ArticleBody, SummaryDraft, SummaryResult


Generate = Callable[[str, str], str]


class LLMSummaryError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def summarize_article(
    article: ArticleBody, *, generate: Generate, model_version: str, is_mock: bool,
) -> SummaryResult:
    """generate(system_prompt, user_prompt)는 JSON 문자열을 반환해야 합니다.

    실제 모델 어댑터 또는 테스트 응답 함수를 연결하는 자리입니다.
    모델 선택·API 인증·통신 제한 시간은 실제 어댑터 단계에서 설정합니다.
    """
    if not isinstance(article, ArticleBody):
        raise TypeError("ArticleBody로 입력을 확인한 뒤 전달해 주세요.")
    if not isinstance(model_version, str) or not model_version.strip() or len(model_version.strip()) > 200:
        raise ValueError("model_version에는 사용할 모델 이름이 필요합니다.")
    if type(is_mock) is not bool:
        raise ValueError("is_mock에는 bool 값을 명시해야 합니다.")
    if not callable(generate):
        raise TypeError("모델 호출 함수를 전달해 주세요.")
    system, user = build_messages(article)
    try:
        raw = generate(system, user)
    except LLMSummaryError:
        # 어댑터에서 분류한 연결·인증·생성 오류를 호출자에게 전달합니다.
        raise
    except TimeoutError:
        raise LLMSummaryError("MODEL_TIMEOUT", "요약 모델 응답 시간이 초과되었습니다.") from None
    except Exception:
        # 원본 예외에 인증 정보나 본문이 들어갈 수 있어 그대로 반환하지 않습니다.
        raise LLMSummaryError("MODEL_CALL_FAILED", "요약 모델 호출에 실패했습니다.") from None
    if not isinstance(raw, str) or len(raw) > 12000:
        raise LLMSummaryError("INVALID_MODEL_OUTPUT", "모델 응답 형식 또는 크기가 올바르지 않습니다.")
    try:
        draft = SummaryDraft.model_validate_json(raw)
    except ValidationError:
        raise LLMSummaryError("INVALID_MODEL_OUTPUT", "요약 JSON 형식을 확인하지 못했습니다.") from None
    if any(bullet.article_ids != [article.id] for bullet in draft.bullets):
        raise LLMSummaryError("INVALID_CITATION", "입력 기사와 요약의 기사 ID가 다릅니다.")
    # 형식·ID 검사가 통과해도 사실성까지 검증된 것은 아닙니다.
    # 본문 근거와 숫자·주체·조건을 검토한 뒤 별도 절차로 공개해야 합니다.
    return SummaryResult(
        article_id=article.id, summary=draft, model_version=model_version.strip(),
        prompt_version=PROMPT_VERSION, is_mock=is_mock, is_demo=article.is_demo,
    )
