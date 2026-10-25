type AnalysisMode = "five_w" | "easy" | "sentiment";
const titles: Record<AnalysisMode, string> = {
  five_w: "확인된 내용을 다섯 가지 질문으로",
  easy: "어려운 뉴스도 쉽게 읽어요",
  sentiment: "기사의 표현은 어떤 어조일까요?",
};

export function AnalysisPanel({ mode, clusterPreview = false }: { mode: AnalysisMode; clusterPreview?: boolean }) {
  return (
    <div className="analysis-state" role="status">
      <span className="overline">MORE WAYS TO READ</span>
      <h3>{titles[mode]}</h3>
      <p>{clusterPreview
        ? "추가 분석 결과를 준비하고 있습니다. 출처 탭에서 원문을 확인해주세요."
        : "분석 결과를 준비하고 있습니다. 지금은 뉴스 DM에서 요약이나 쉬운 설명을 요청할 수 있어요."}</p>
    </div>
  );
}
