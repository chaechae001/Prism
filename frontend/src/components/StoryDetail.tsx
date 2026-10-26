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
import { ContextPanel } from "./ContextPanel";
import { isLocalClusterStory, clusterSourceLabel } from "../presentation/clusterPreview";

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
  const activeTab = tab === "perspectives" || (tab === "summary" && story?.summary.status !== "ready") ? "five_w" : tab;
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
              ? "기사의 핵심을 읽고 원문 출처를 확인하세요."
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
                <Tabs.Root value={activeTab} onValueChange={setTab}>
                  <Tabs.List className="detail-tabs" aria-label="사건 내용">
                    {story.summary.status === "ready" && <Tabs.Trigger value="summary">핵심 요약</Tabs.Trigger>}
                    <Tabs.Trigger value="five_w">팩트 5W</Tabs.Trigger>
                    <Tabs.Trigger value="easy">쉽게 읽기</Tabs.Trigger>
                    <Tabs.Trigger value="sentiment">감정·어조</Tabs.Trigger>
                    <Tabs.Trigger value="context">자료 확인</Tabs.Trigger>
                    <Tabs.Trigger value="sources">
                      출처 <span>{story.articles.length}</span>
                    </Tabs.Trigger>
                  </Tabs.List>
                  {story.summary.status === "ready" && <Tabs.Content value="summary" className="detail-panel">
                    <ol className="summary-bullets">{story.summary.bullets.map((bullet,i)=><li key={i}><span className="bullet-number">0{i+1}</span><div>{bullet.text}<button className="citation-button" onClick={()=>cited(bullet.article_ids)}>출처 확인 ↗</button></div></li>)}</ol>
                  </Tabs.Content>}
                  {(["five_w", "easy", "sentiment"] as const).map((mode) => (
                    <Tabs.Content
                      value={mode}
                      className="detail-panel"
                      key={mode}
                    >
                      <AnalysisPanel mode={mode} storyId={story.id} revision={story.updated_at} onCite={cited} clusterPreview={clusterPreview} />
                    </Tabs.Content>
                  ))}
                  <Tabs.Content value="context" className="detail-panel"><ContextPanel key={story.id} storyId={story.id}/></Tabs.Content>
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
                            {a.publisher_name} · {clusterPreview ? clusterSourceLabel(a.framing) : a.framing}
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
                      추가 정보가 필요해요
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
