import { useState } from "react";
import {
  Bookmark,
  ChevronDown,
  Ellipsis,
  Layers3,
  MessageCircle,
  Send,
} from "lucide-react";
import type { FeedItem } from "../api/types";
import { categoryNames, type DetailTab } from "../presentation/timeline";
import { NewsPhoto } from "./NewsPhoto";

export function SocialPost({
  item,
  saved,
  onSave,
  onOpen,
  onComments,
  onDm,
  commentCount,
}: {
  item: FeedItem;
  saved: boolean;
  onSave: () => void;
  onOpen: (tab?: DetailTab) => void;
  onComments: () => void;
  onDm: () => void;
  commentCount: number;
}) {
  const { story } = item;
  const [expanded, setExpanded] = useState(false);
  const ready = story.summary.status === "ready";
  const text = ready
    ? story.summary.bullets.map((b) => b.text).join(" ") || story.dek
    : story.dek;
  const publishers = [...new Set(story.articles.map((a) => a.publisher_name))];
  return (
    <article className="social-post">
      <header className="post-header">
        <span className="post-avatar">
          p<span>·</span>
        </span>
        <div>
          <strong>
            prism.news{" "}
            <span className="verified-mark" aria-label="프리즘 뉴스">
              ✳
            </span>
          </strong>
          <small>
            {categoryNames[story.category]} ·{" "}
            {new Intl.DateTimeFormat("ko-KR", {
              month: "long",
              day: "numeric",
              timeZone: "Asia/Seoul",
            }).format(new Date(story.updated_at))}
            {story.is_demo ? " · 가상 뉴스" : ""}
          </small>
        </div>
        <button
          className="social-icon post-more"
          aria-label={`${story.title} 출처 보기`}
          onClick={() => onOpen("sources")}
        >
          <Ellipsis />
        </button>
      </header>
      <button
        className="post-image-button"
        onClick={() => onOpen()}
        aria-label={`${story.title} 상세 보기`}
      >
        <NewsPhoto story={story} />
        <span className="post-image-badge">
          <Layers3 size={13} />
          {story.coverage.article_count}개 기사
        </span>
      </button>
      <div className="post-actions">
        <button
          className="social-icon"
          onClick={() => onOpen("perspectives")}
          aria-label={`${story.title} 다른 관점 보기`}
        >
          <Layers3 />
        </button>
        <button
          className="social-icon"
          onClick={onComments}
          aria-label={`${story.title} 댓글 보기`}
        >
          <MessageCircle />
        </button>
        <button
          className="social-icon"
          onClick={onDm}
          aria-label={`${story.title} DM 시작`}
        >
          <Send />
        </button>
        <button
          className="social-icon post-save"
          onClick={onSave}
          aria-label={`${story.title} ${saved ? "저장 취소" : "저장"}`}
          aria-pressed={saved}
        >
          <Bookmark fill={saved ? "currentColor" : "none"} />
        </button>
      </div>
      <div className="post-copy">
        <button className="post-coverage" onClick={() => onOpen("sources")}>
          <span className="tiny-avatars">
            {publishers.slice(0, 3).map((p, i) => (
              <i key={p} className={`tiny-${i}`}>
                {p.replace(/^(데모|가상)\s*/, "").slice(0, 1)}
              </i>
            ))}
          </span>
          <span>
            <strong>{story.coverage.publisher_count}개 매체</strong>가 함께 전한
            이야기
          </span>
        </button>
        <h2>
          <button onClick={() => onOpen()}>{story.title}</button>
        </h2>
        <p className={expanded ? "post-caption expanded" : "post-caption"}>
          <b>{ready ? "AI 요약" : "기사 미리보기"}</b>{" "}
          {text || "요약을 준비하고 있습니다. 원문을 확인해주세요."}
        </p>
        {text.length > 90 && (
          <button
            className="caption-more"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "접기" : "더 보기"}
            <ChevronDown size={12} />
          </button>
        )}
        <button className="post-all-sources" onClick={() => onOpen("sources")}>
          관련 기사 {story.coverage.article_count}개 모두 보기
        </button>
        <button className="post-all-sources" onClick={onComments}>
          댓글 {commentCount}개 보기
        </button>
      </div>
    </article>
  );
}
