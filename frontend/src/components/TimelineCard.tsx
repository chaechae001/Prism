import { ArrowRight, ArrowUpRight, Bookmark, Layers3 } from "lucide-react";
import type { FeedItem } from "../api/types";
import { categoryNames, type DetailTab } from "../presentation/timeline";
import { statusNames } from "./StoryDetail";

const timeFormat = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function TimelineCard({
  item,
  featured = false,
  preview = false,
  saved,
  onSave,
  onOpen,
}: {
  item: FeedItem;
  featured?: boolean;
  preview?: boolean;
  saved: boolean;
  onSave: () => void;
  onOpen: (tab?: DetailTab) => void;
}) {
  const { story } = item;
  const publishers = [
    ...new Map(
      story.articles.map((article) => [
        article.publisher_id,
        article.publisher_name,
      ]),
    ).entries(),
  ];
  const ready = story.summary.status === "ready";
  const openSources = () => onOpen("sources");
  return (
    <article className={`news-card ${featured ? "featured" : ""}`}>
      {featured && (
        <div className="focus-line">
          <span>
            <span className="focus-dot" />
            먼저 읽을 이야기
          </span>
          <span>IN FOCUS</span>
        </div>
      )}
      <div className="news-meta">
        <span className="category-label">{categoryNames[story.category]}</span>
        <span className="collected-count">
          <Layers3 size={13} />
          {story.coverage.article_count}개 기사
        </span>
        <time className="news-update" dateTime={story.updated_at}>
          {timeFormat.format(new Date(story.updated_at))}
        </time>
        <button
          className={`icon-button bookmark-button ${saved ? "saved" : ""}`}
          aria-label={`${story.title} ${saved ? "저장 취소" : "저장"}`}
          aria-pressed={saved}
          onClick={onSave}
        >
          <Bookmark
            size={19}
            fill={saved ? "currentColor" : "none"}
            strokeWidth={1.6}
          />
        </button>
      </div>
      <h2>
        <button
          onClick={() => onOpen(preview || !ready ? "sources" : "summary")}
        >
          {story.title}
        </button>
      </h2>
      <section
        className={`timeline-summary ${ready ? "" : "is-pending"}`}
        aria-label={statusNames[story.summary.status]}
      >
        <div className="timeline-summary-label">
          <span className="summary-glyph" aria-hidden="true">
            ✳
          </span>
          {preview
            ? "원문 미리보기"
            : ready
              ? "사건의 맥락"
              : statusNames[story.summary.status]}
          {story.is_demo && <small>가상 자료</small>}
        </div>
        <p>
          {ready
            ? story.summary.bullets
                .slice(0, 1)
                .map((bullet) => bullet.text)
                .join(" ") || story.dek
            : story.dek}
        </p>
        {!ready && (
          <span className="summary-state-note">
            {preview
              ? "기사 1건 · 군집분석과 AI 요약 전입니다."
              : "요약이 준비되기 전까지 원문을 확인해주세요."}
          </span>
        )}
      </section>
      <div className="source-ribbon">
        <button
          className="source-collection"
          onClick={openSources}
          aria-label={`${story.coverage.publisher_count}개 매체의 원문 보기`}
        >
          <span className="source-avatars" aria-hidden="true">
            {publishers.slice(0, 3).map(([id, name], index) => (
              <span className={`source-avatar avatar-${index}`} key={id}>
                {name.replace(/^(데모|가상)\s*/, "").slice(0, 1)}
              </span>
            ))}
          </span>
          <span>
            <strong>{story.coverage.publisher_count}개 매체</strong>
            <span>
              {preview
                ? "원문 출처 확인"
                : story.coverage.publisher_count > 1
                  ? "같은 사건, 다른 시선"
                  : "단일 출처 · 추가 확인 중"}
            </span>
          </span>
          <ArrowUpRight size={15} />
        </button>
      </div>
      {ready && story.perspectives.length > 1 && (
        <div className="perspective-previews" aria-label="보도의 쟁점 미리보기">
          {story.perspectives.slice(0, 2).map((perspective, index) => (
            <button
              className={`perspective-preview preview-${index}`}
              key={`${index}-${perspective.label}`}
              onClick={() => onOpen("perspectives")}
            >
              <span className="perspective-index">0{index + 1}</span>
              <strong>{perspective.label}</strong>
              <ArrowUpRight size={13} />
              {featured && (
                <span className="perspective-description">
                  {perspective.text}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
      <div className="publisher-cloud" aria-label="보도 매체">
        {publishers.slice(0, 5).map(([id, name]) => (
          <button key={id} onClick={openSources}>
            {name}
            <ArrowUpRight size={10} />
          </button>
        ))}
        {publishers.length > 5 && (
          <button onClick={openSources}>+{publishers.length - 5}</button>
        )}
      </div>
      <div className="card-bottom">
        <span>
          {preview
            ? "AI 분석 전"
            : `${story.perspectives.length}개 쟁점${story.coverage.label_status !== "reviewed" ? " · 분류 미검증" : " · 검토됨"}`}
        </span>
        <button
          className="card-cta"
          onClick={() => onOpen(preview || !ready ? "sources" : "summary")}
        >
          {preview || !ready ? "원문 살펴보기" : "맥락 읽기"}
          <ArrowRight size={15} />
        </button>
      </div>
    </article>
  );
}
