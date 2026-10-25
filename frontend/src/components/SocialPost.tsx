import {
  Bookmark,
  Ellipsis,
  Layers3,
  MessageCircle,
  Send,
} from "lucide-react";
import type { FeedItem } from "../api/types";
import { categoryNames, type DetailTab } from "../presentation/timeline";
import { NewsPhoto } from "./NewsPhoto";
import { ArticleCaption } from './ArticleCaption';
import { isLocalClusterStory, isDbClusterStory } from "../presentation/clusterPreview";

export function SocialPost({
  item,
  saved,
  onSave,
  onOpen,
  onComments,
  onDm,
  commentCount,
  clusterPreview: feedClusterPreview = false,
}: {
  item: FeedItem;
  saved: boolean;
  onSave: () => void;
  onOpen: (tab?: DetailTab) => void;
  onComments: () => void;
  onDm: () => void;
  commentCount: number;
  clusterPreview?: boolean;
}) {
  const { story } = item;
  const clusterPreview = feedClusterPreview || isLocalClusterStory(story);
  const ready = story.summary.status === "ready" && (!clusterPreview || isDbClusterStory(story));
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
            <span className="post-category">{categoryNames[story.category]}</span>{" "}
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
        <span className="post-photo-title">{story.title}</span>
        <span className="post-image-badge">
          <Layers3 size={13} />
          {story.coverage.article_count}개 기사
        </span>
      </button>
      <div className="post-actions">
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
            <strong>{story.coverage.publisher_count}개 매체</strong>
            {clusterPreview ? " · 보도 출처" : "가 함께 전한 이야기"}
          </span>
        </button>
        <ArticleCaption story={story} ready={ready} clusterPreview={clusterPreview}/>
        {clusterPreview && story.summary.unknowns.filter((note) => note.startsWith("검토 필요:") && !note.includes("군집 품질 점검")).map((note) => (
          <p className="cluster-review-warning" key={note}>{note}</p>
        ))}
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
