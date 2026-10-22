"""Implement these protocols in analyst code; request handlers only read stored output."""

from typing import Protocol
from .models import AnalysisArticle, AnalysisMode, AnalysisOutput, ClusterOutput


class ClusterProvider(Protocol):
    model_version: str

    def cluster(self, articles: list[AnalysisArticle]) -> list[ClusterOutput]: ...


class ModeProvider(Protocol):
    model_version: str
    prompt_version: str

    async def generate(
        self, mode: AnalysisMode, articles: list[AnalysisArticle]
    ) -> AnalysisOutput: ...


async def generate_mode(
    provider: ModeProvider, mode: AnalysisMode, articles: list[AnalysisArticle]
):
    permission = "analyze" if mode == "sentiment" else "summarize"
    if not articles or any(not getattr(a.rights, permission) for a in articles):
        raise ValueError("ANALYSIS_USE_NOT_ALLOWED")
    result = AnalysisOutput.model_validate(await provider.generate(mode, articles))
    if result.mode != mode:
        raise ValueError("PROVIDER_MODE_MISMATCH")
    return result
