import * as Dialog from "@radix-ui/react-dialog";
import * as Tabs from "@radix-ui/react-tabs";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Bookmark,
  Check,
  Flag,
  Layers3,
  ThumbsUp,
  X,
} from "lucide-react";
import { api, ApiError } from "../api/client";
import type { FeedbackRequest, Story } from "../api/types";
import type { DetailTab } from "../presentation/timeline";
import { AnalysisPanel } from "./AnalysisPanel";
import { NewsPhoto } from "./NewsPhoto";
import { isLocalClusterStory, isDbClusterStory } from "../presentation/clusterPreview";

const categoryNames = {
  politics: "정치",
  economy: "경제",
  society: "사회",
  technology: "기술",
};
export const statusNames = {
  ready: "AI 요약",
  pending: "요약 준비 중",
  insufficient_sources: "추가 출처 확인 중",
  failed: "요약 생성 실패",
};

export function StoryDetail({
  id,
  onClose,
  saved,
  onSave,
  initialTab = "summary",
  onRead,
  clusterPreview: feedClusterPreview = false,
}: {
  id: string | null;
  onClose: () => void;
  saved: boolean;
  onSave: (id: string) => void;
  initialTab?: DetailTab;
  onRead?: (story: Story) => void;
  clusterPreview?: boolean;
}) {
  const query = useQuery({
    queryKey: ["story", id],
    queryFn: ({ signal }) => api.story(id!, signal),
    enabled: !!id,
    refetchInterval: id?.startsWith("db-cluster-") ? 60_000 : false,
  });
  const [tab, setTab] = useState<string>(initialTab);
  const returnFocus = useRef(document.activeElement as HTMLElement | null);
  const [highlight, setHighlight] = useState<string[]>([]);
  const feedback = useMutation({
    mutationFn: (kind: FeedbackRequest["kind"]) =>
      api.feedback({ story_id: id!, kind }),
  });
  const story = query.data?.story;
  const clusterPreview = feedClusterPreview || isLocalClusterStory(story);
  useEffect(() => {
    if (story) onRead?.(story);
  }, [story, onRead]);
  const cited = (ids: string[]) => {
    setHighlight(ids);
    setTab("sources");
  };
  return (
    <Dialog.Root
      open={!!id}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="dialog-content"
          aria-describedby="story-dialog-description"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            returnFocus.current?.focus();
          }}
        >
          <Dialog.Close
            className="icon-button dialog-close"
            aria-label="상세 닫기"
          >
            <X size={21} />
          </Dialog.Close>
          <p className="eyebrow">PRISM BRIEFING</p>
          <Dialog.Title className="detail-title">
            {story?.title || "사건 불러오는 중"}
          </Dialog.Title>
          <Dialog.Description id="story-dialog-description" className="muted">
            {clusterPreview
              ? "군집에 포함된 기사와 원문 출처를 확인하세요. 동일 사건 여부는 검토 전입니다."
              : "여러 출처를 함께 읽고, 서로 다른 시선을 발견하세요."}
            {story?.is_demo ? " 현재 내용은 가상 데모 자료입니다." : ""}
          </Dialog.Description>
          {query.isPending ? (
            <div
              className="skeleton detail-skeleton"
              aria-label="불러오는 중"
            />
          ) : query.isError ? (
            <div className="state-box" role="alert">
              {query.error.message}
              <p>
                {query.error instanceof ApiError
                  ? `요청 ID: ${query.error.requestId}`
                  : ""}
              </p>
              <button className="button" onClick={() => query.refetch()}>
                다시 시도
              </button>
            </div>
          ) : (
            story && (
              <>
                <div className="detail-meta">
                  <span className="category-label">
                    {categoryNames[story.category]}
                  </span>
                  <span>
                    {story.coverage.article_count}개 기사 ·{" "}
                    {story.coverage.publisher_count}개 출처
                  </span>
                  <button
                    className={`icon-button ${saved ? "saved" : ""}`}
                    onClick={() => onSave(story.id)}
                    aria-label={saved ? "저장 취소" : "사건 저장"}
                    aria-pressed={saved}
                  >
                    <Bookmark
                      size={19}
                      fill={saved ? "currentColor" : "none"}
                    />
                  </button>
                </div>
                <Tabs.Root value={tab} onValueChange={setTab}>
                  <Tabs.List className="detail-tabs" aria-label="사건 내용">
                    <Tabs.Trigger value="summary">{clusterPreview ? "대표기사" : "핵심 요약"}</Tabs.Trigger>
                    <Tabs.Trigger value="five_w">팩트 5W</Tabs.Trigger>
                    <Tabs.Trigger value="easy">쉽게 읽기</Tabs.Trigger>
                    <Tabs.Trigger value="sentiment">감정·어조</Tabs.Trigger>
                    <Tabs.Trigger value="perspectives">
                      관점 비교 <span>{story.perspectives.length}</span>
                    </Tabs.Trigger>
                    <Tabs.Trigger value="sources">
                      출처 <span>{story.articles.length}</span>
                    </Tabs.Trigger>
                  </Tabs.List>
                  <Tabs.Content value="summary" className="detail-panel">
                    {story.articles[0]?.image_url && (
                      <div className="detail-article-photo"><NewsPhoto story={story} /></div>
                    )}
                    <div className="summary-label">
                      <span className="sparkle">✧</span>{" "}
                      {isDbClusterStory(story) ? "대표기사 · 원문 출처" : clusterPreview ? "대표기사 본문 발췌" : statusNames[story.summary.status]}
                      {story.is_demo && <span className="tiny-tag">데모</span>}
                    </div>
                    {clusterPreview ? (
                      <div className="notice">
                        <strong>{isDbClusterStory(story) ? "AI 요약 미생성 · 군집 대표기사" : "AI 요약 미생성 · 원문 발췌"}</strong>
                        <p>{story.dek}</p>
                        <button className="citation-button" onClick={() => setTab("sources")}>
                          대표기사와 관련 기사 {story.articles.length}개 확인 ↗
                        </button>
                      </div>
                    ) : story.summary.status === "ready" ? (
                      <ol className="summary-bullets">
                        {story.summary.bullets.map((bullet, i) => (
                          <li key={i}>
                            <span className="bullet-number">0{i + 1}</span>
                            <div>
                              {bullet.text}
                              <button
                                className="citation-button"
                                onClick={() => cited(bullet.article_ids)}
                              >
                                출처 {bullet.article_ids.length}개 확인 ↗
                              </button>
                            </div>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <div className="notice">
                        <strong>{statusNames[story.summary.status]}</strong>
                        <p>
                          {story.summary.status === "insufficient_sources"
                            ? "독립적인 출처가 부족해 요약을 보류했습니다."
                            : story.summary.status === "failed"
                              ? "처리 중 오류가 발생했습니다. 원문 목록은 출처 탭에서 확인할 수 있습니다."
                              : "검토가 끝나면 근거를 연결한 요약을 제공합니다."}
                        </p>
                      </div>
                    )}
                    <div className="unknowns">
                      <strong>아직 확인할 내용</strong>
                      {story.summary.unknowns.map((t) => (
                        <p key={t}>{t}</p>
                      ))}
                    </div>
                    <div className="detail-note">
                      {clusterPreview
                        ? isDbClusterStory(story) ? "군집 후보와 원문 출처를 제공합니다. 동일 사건 여부는 검토 전입니다." : "표시된 발췌는 자동 요약이 아닙니다. 원문과 함께 확인해주세요."
                        : "AI 요약은 사실 확인을 대신하지 않습니다. 원문과 다른 부분은 알려주세요."}
                    </div>
                  </Tabs.Content>
                  {(["five_w", "easy", "sentiment"] as const).map((mode) => (
                    <Tabs.Content
                      value={mode}
                      className="detail-panel"
                      key={mode}
                    >
                      <AnalysisPanel mode={mode} clusterPreview={clusterPreview} />
                    </Tabs.Content>
                  ))}
                  <Tabs.Content value="perspectives" className="detail-panel">
                    <p className="muted small">
                      아래 구분은 기사에서 강조하는 쟁점입니다. 언론사의 정치
                      성향을 뜻하지 않습니다.{" "}
                      {story.coverage.label_status === "demo"
                        ? "데모 라벨이며 검증된 분류가 아닙니다."
                        : story.coverage.label_status === "unverified"
                          ? "아직 검토되지 않은 분류입니다."
                          : "검토된 쟁점 분류입니다."}
                    </p>
                    {story.perspectives.length ? (
                      story.perspectives.map((p, i) => (
                        <div
                          className={`perspective perspective-${i}`}
                          key={p.label}
                        >
                          <span className="eyebrow">VIEW 0{i + 1}</span>
                          <h3>{p.label}</h3>
                          <p>{p.text}</p>
                          <button
                            className="citation-button"
                            onClick={() => cited(p.article_ids)}
                          >
                            근거 기사 보기 ↗
                          </button>
                        </div>
                      ))
                    ) : (
                      <div className="state-box">
                        관점 비교를 위한 자료를 준비하고 있습니다.
                      </div>
                    )}
                  </Tabs.Content>
                  <Tabs.Content value="sources" className="detail-panel">
                    <p className="muted small">
                      {story.is_demo
                        ? "가상 언론사와 example.com 링크입니다. 실제 뉴스 원문으로 연결되지 않습니다."
                        : "제목을 누르면 해당 언론사의 원문으로 이동합니다."}
                    </p>
                    {story.articles.map((a) => (
                      <a
                        className={`source-row ${highlight.includes(a.id) ? "highlight" : ""}`}
                        key={a.id}
                        href={a.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <span className="source-initial">
                          {a.publisher_name.replace(/^데모\s*/, "").slice(0, 1)}
                        </span>
                        <div>
                          <span className="source-name">
                            {a.publisher_name} · {a.framing}
                          </span>
                          <h3>{a.title}</h3>
                          <span className="muted small">
                            {new Intl.DateTimeFormat("ko-KR", {
                              timeZone: "Asia/Seoul",
                              month: "long",
                              day: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                            }).format(new Date(a.published_at))}
                            {a.is_demo ? " · 가상 기사" : ""}
                          </span>
                        </div>
                        <ArrowUpRight size={18} />
                      </a>
                    ))}

                  </Tabs.Content>
                </Tabs.Root>
                <div className="feedback">
                  <span>이 브리핑은 어땠나요?</span>
                  <div>
                    <button
                      disabled={feedback.isPending}
                      onClick={() => feedback.mutate("useful")}
                    >
                      <ThumbsUp size={15} />
                      도움이 됐어요
                    </button>
                    <button
                      disabled={feedback.isPending}
                      onClick={() => feedback.mutate("more_perspectives")}
                    >
                      <Layers3 size={15} />
                      다른 관점이 필요해요
                    </button>
                    <button
                      disabled={feedback.isPending}
                      onClick={() => feedback.mutate("report_error")}
                    >
                      <Flag size={15} />
                      오류 제보
                    </button>
                  </div>
                  <p role="status" className="small">
                    {feedback.isSuccess ? (
                      <>
                        <Check size={14} />{" "}
                        {feedback.data.persisted
                          ? "피드백을 저장했습니다."
                          : "데모 응답을 받았습니다. 피드백은 영구 저장되지 않습니다."}
                      </>
                    ) : feedback.isError ? (
                      "피드백을 전송하지 못했습니다. 다시 시도해주세요."
                    ) : feedback.isPending ? (
                      "전송 중…"
                    ) : (
                      ""
                    )}
                  </p>
                </div>
              </>
            )
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
