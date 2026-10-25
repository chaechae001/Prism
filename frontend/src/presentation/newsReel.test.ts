import { describe, expect, it } from "vitest";
import { reelExcerpt } from "./newsReel";

describe("story excerpt", () => {
  it("reduces a long body to roughly one third without altering the source", () => {
    const source = "가나다라마".repeat(48);
    expect(reelExcerpt(source)).toBe(source.slice(0, 80) + "…");
    expect(source.length).toBe(240);
  });
  it("removes the excerpt label and preserves short text and Unicode characters", () => {
    expect(reelExcerpt("대표기사 본문 발췌 · 짧은 뉴스입니다.")).toBe("짧은 뉴스입니다.");
    expect(reelExcerpt("📰".repeat(90))).toBe("📰".repeat(30) + "…");
    expect(reelExcerpt("")).toBe("");
  });
});
