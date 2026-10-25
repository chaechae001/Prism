import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SocialPost } from "../components/SocialPost";
import { clusterSourceLabel, isDbClusterStory } from "./clusterPreview";
import { stories } from "../mocks/policy";

describe("DB cluster candidates", () => {
  it("keeps source labels without showing review-state badges or claiming generated summaries", () => {
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
    expect(html).not.toContain("동일 사건 검토 전");
    expect(html).toContain("대표기사 · 원문 출처");
    expect(html).not.toContain("대표기사 발췌");
    expect(html).not.toContain("AI 요약");
    expect(html).not.toContain("images.unsplash.com");
  });
});

describe("cluster source display", () => {
  it("recognizes DB articles returned through a legacy saved story link", () => {
    const story = structuredClone(stories[0]);
    story.id = "local-cluster-80cef8ab151645a8c1319435";
    story.articles[0].publisher_id = "cluster-publisher-example";
    expect(isDbClusterStory(story)).toBe(true);
    expect(isDbClusterStory({id:story.id})).toBe(false);
  });
  it("hides the review-state suffix while preserving the original API data", () => {
    const framing = "대표기사 · 동일 사건 검토 전";
    expect(clusterSourceLabel(framing)).toBe("대표기사");
    expect(framing).toBe("대표기사 · 동일 사건 검토 전");
    expect(clusterSourceLabel("군집 관련 기사 · 동일 사건 검토 전")).toBe("군집 관련 기사");
  });
});
