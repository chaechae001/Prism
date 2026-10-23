import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SocialPost } from "./SocialPost";
import { stories } from "../mocks/policy";
import type { FeedItem } from "../api/types";

function render(clusterPreview: boolean, demo = false, warning = false, localIdentity = false) {
  const story = structuredClone(stories[0]);
  if (localIdentity) story.id = "local-cluster-80cef8ab151645a8c1319435";
  story.is_demo = demo;
  story.dek = "대표기사 본문 발췌 · 실제 제공 본문의 앞부분입니다.";
  story.coverage.publisher_count = 1;
  if (!demo) {
    story.summary.status = "pending";
    story.summary.bullets = [];
    story.coverage.label_status = "unverified";
  }
  story.summary.unknowns = warning ? ["검토 필요: 본문 재사용을 확인해주세요."] : [];
  const item: FeedItem = { story, reason: { code: "latest", label: "최근 뉴스" } };
  return renderToStaticMarkup(
    <SocialPost item={item} clusterPreview={clusterPreview} saved={false}
      onSave={vi.fn()} onOpen={vi.fn()} onComments={vi.fn()} onDm={vi.fn()} commentCount={0} />,
  );
}

describe("local cluster feed cards", () => {
  it("labels the representative excerpt and keeps real stories free of demo images", () => {
    const html = render(true);
    expect(html).toContain("대표기사 발췌");
    expect(html).toContain("동일 사건 검토 전");
    expect(html).toContain("보도 출처");
    expect(html).not.toContain("AI 요약");
    expect(html).not.toContain("images.unsplash.com");
  });
  it("surfaces the saved review warning without changing the article text", () => {
    expect(render(true, false, true)).toContain("검토 필요: 본문 재사용을 확인해주세요.");
    expect(render(true)).toContain("실제 제공 본문의 앞부분입니다.");
  });
  it("retains the existing fictional summary and photography in demo mode", () => {
    const html = render(false, true);
    expect(html).toContain("AI 요약");
    expect(html).toContain("images.unsplash.com");
    expect(html).not.toContain("동일 사건 검토 전");
  });
  it("retains excerpt and review labels when a saved local story has no feed metadata", () => {
    const html = render(false, false, true, true);
    expect(html).toContain("대표기사 발췌");
    expect(html).toContain("동일 사건 검토 전");
    expect(html).toContain("검토 필요: 본문 재사용을 확인해주세요.");
  });
});
