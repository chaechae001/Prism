import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { NewsPhoto } from "./NewsPhoto";
import { stories } from "../mocks/policy";

describe("representative article photos", () => {
  it("renders the real representative image with article attribution instead of stock photography", () => {
    const story = structuredClone(stories[0]);
    story.is_demo = false;
    story.articles[0].image_url = "https://img.sbs.co.kr/news/article.jpg";
    const html = renderToStaticMarkup(<NewsPhoto story={story} />);
    expect(html).toContain('src="https://img.sbs.co.kr/news/article.jpg"');
    expect(html).toContain(story.articles[0].publisher_name);
    expect(html).toContain("기사 이미지");
    expect(html).not.toContain("images.unsplash.com");
  });
  it("keeps a placeholder when only a related article has an image", () => {
    const story = structuredClone(stories[0]);
    story.is_demo = false;
    story.articles[0].image_url = null;
    story.articles[1].image_url = "https://img.example.org/related.jpg";
    const html = renderToStaticMarkup(<NewsPhoto story={story} />);
    expect(html).toContain("기사 사진이 제공되지 않았습니다");
    expect(html).not.toContain("related.jpg");
  });
  it("preserves demo photo labels and hides overlay text in compact views", () => {
    const story = structuredClone(stories[0]);
    const demo = renderToStaticMarkup(<NewsPhoto story={story} />);
    expect(demo).toContain("예시 사진 · 실제 사건 사진 아님");
    const compact = renderToStaticMarkup(<NewsPhoto story={story} compact />);
    expect(compact).not.toContain('class="photo-disclaimer"');
  });
});
