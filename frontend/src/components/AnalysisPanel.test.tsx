import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { AnalysisPanel } from "./AnalysisPanel";

describe("analysis availability for saved local clusters", () => {
  it.each(["five_w", "easy", "sentiment"] as const)("does not direct local %s analysis to disabled chat", (mode) => {
    const html = renderToStaticMarkup(<AnalysisPanel mode={mode} clusterPreview />);
    expect(html).toContain("추가 분석 결과를 준비하고 있습니다");
    expect(html).toContain("출처 탭에서 원문을 확인해주세요");
    expect(html).not.toContain("요청할 수 있어요");
  });
  it("preserves the existing analysis guidance for other sources", () => {
    const html = renderToStaticMarkup(<AnalysisPanel mode="easy" />);
    expect(html).toContain("뉴스 DM에서 요약이나 쉬운 설명을 요청할 수 있어요");
  });
});
