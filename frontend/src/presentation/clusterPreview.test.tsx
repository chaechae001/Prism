import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SocialPost } from "../components/SocialPost";
import { stories } from "../mocks/policy";

describe("DB cluster candidates", () => {
  it("keeps review labels in saved cards without claiming an excerpt or generated summary", () => {
    const story = structuredClone(stories[0]);
    story.id = "db-cluster-80cef8ab151645a8c1319435";
    story.is_demo = false;
    story.summary.status = "pending";
    story.summary.bullets = [];
    story.dek = "관련 기사 2개 · 대표기사와 출처를 확인하세요.";
    const html = renderToStaticMarkup(<SocialPost
      item={{story, reason:{code:"latest",label:"최신"}}} saved={false}
      onSave={vi.fn()} onOpen={vi.fn()} onComments={vi.fn()} onDm={vi.fn()} commentCount={0}
    />);
    expect(html).toContain("동일 사건 검토 전");
    expect(html).toContain("대표기사 · 원문 출처");
    expect(html).not.toContain("대표기사 발췌");
    expect(html).not.toContain("AI 요약");
    expect(html).not.toContain("images.unsplash.com");
  });
});
