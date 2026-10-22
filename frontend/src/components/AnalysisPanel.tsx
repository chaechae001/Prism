import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import { api, apiVersion } from "../api/client";
import type { AnalysisMode } from "../api/newsTypes";
import type { Story } from "../api/types";

type Claim = { text: string; article_ids: string[] };
const claim = (v: unknown): v is Claim =>
  !!v &&
  typeof v === "object" &&
  "text" in v &&
  typeof v.text === "string" &&
  "article_ids" in v &&
  Array.isArray(v.article_ids) &&
  v.article_ids.every((id) => typeof id === "string");
const claims = (v: unknown) => (Array.isArray(v) ? v.filter(claim) : []);
const titles = {
  five_w: "확인된 내용을 다섯 가지 질문으로",
  easy: "어려운 뉴스도 쉽게 읽어요",
  sentiment: "기사의 표현은 어떤 어조일까요?",
};

export function AnalysisPanel({
  story,
  mode,
  onCite,
}: {
  story: Story;
  mode: Exclude<AnalysisMode, "summary">;
  onCite: (ids: string[]) => void;
}) {
  const query = useQuery({
    queryKey: ["analysis", story.id, mode],
    queryFn: ({ signal }) => api.analysis(story.id, mode, signal),
    enabled: apiVersion === "v2",
    retry: false,
  });
  const output = query.data;
  const payload = output?.payload;
  const source = (value: Claim) => (
    <button
      className="citation-button"
      onClick={() => onCite(value.article_ids)}
    >
      근거 {value.article_ids.length}개 확인 <ArrowUpRight size={12} />
    </button>
  );
  if (apiVersion !== "v2")
    return (
      <div className="analysis-state">
        <span className="overline">MORE WAYS TO READ</span>
        <h3>{titles[mode]}</h3>
        <p>
          분석 모드 연결을 준비하고 있습니다. v2 API에 검토된 결과를 연결하면 이
          탭에서 볼 수 있습니다.
        </p>
        <p className="small muted">
          지금 화면에서 분석 모델이나 LLM을 실행하지 않습니다.
        </p>
      </div>
    );
  if (query.isPending)
    return (
      <div className="analysis-state" role="status">
        저장된 분석 결과를 불러오고 있어요.
      </div>
    );
  if (query.isError)
    return (
      <div className="analysis-state" role="alert">
        <p>분석 결과를 불러오지 못했어요.</p>
        <button className="text-button" onClick={() => query.refetch()}>
          다시 시도
        </button>
      </div>
    );
  if (output?.status !== "ready" || !payload)
    return (
      <div className="analysis-state">
        <h3>
          {output?.status === "failed"
            ? "분석 중 오류가 발생했어요."
            : output?.status === "insufficient_sources"
              ? "분석할 근거가 부족해요."
              : "분석 결과를 준비하고 있어요."}
        </h3>
        <p>{output?.notice}</p>
      </div>
    );
  return (
    <div className="analysis-mode">
      <div className="analysis-intro">
        <span className="overline">
          {mode === "five_w"
            ? "FACTS IN CONTEXT"
            : mode === "easy"
              ? "READ IT SIMPLY"
              : "LANGUAGE & TONE"}
        </span>
        <h3>{titles[mode]}</h3>
        {output.is_demo && (
          <span className="quiet-badge">가상 분석 결과 · 모델 실행 아님</span>
        )}
      </div>
      {mode === "five_w" && (
        <dl className="five-w-grid">
          {(
            [
              ["who", "누가"],
              ["what", "무엇을"],
              ["when", "언제"],
              ["where", "어디서"],
              ["why", "왜"],
            ] as const
          ).map(([key, label]) => {
            const value = payload[key];
            return (
              <div key={key}>
                <dt>
                  {label}
                  <span>{key.toUpperCase()}</span>
                </dt>
                <dd>
                  {claim(value) ? (
                    <>
                      {value.text}
                      {source(value)}
                    </>
                  ) : (
                    <span className="muted">확인된 근거가 없습니다.</span>
                  )}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
      {mode === "easy" && (
        <>
          <div className="easy-paragraphs">
            {claims(payload.paragraphs).map((value, index) => (
              <div key={index}>
                <p>{value.text}</p>
                {source(value)}
              </div>
            ))}
          </div>
          {claims(payload.glossary).length > 0 && (
            <div className="unknowns">
              <strong>낱말 풀이</strong>
              {claims(payload.glossary).map((value, index) => (
                <div key={index}>
                  <p>{value.text}</p>
                  {source(value)}
                </div>
              ))}
            </div>
          )}
        </>
      )}
      {mode === "sentiment" && (
        <>
          <p className="notice">
            기사의 표현상 어조를 분석합니다. 사건의 진위·정치 성향·독자의 감정을
            평가하는 점수가 아닙니다.
          </p>
          {Array.isArray(payload.observations) &&
            payload.observations.map((value, index) => {
              if (!value || typeof value !== "object") return null;
              const row = value as Record<string, unknown>;
              const id =
                typeof row.article_id === "string" ? row.article_id : "";
              const article = story.articles.find((a) => a.id === id);
              const labels: Record<string, string> = {
                positive: "긍정적 표현",
                negative: "부정적 표현",
                neutral: "중립적 표현",
                mixed: "복합적 표현",
              };
              return (
                <div className="sentiment-row" key={index}>
                  <div>
                    <strong>
                      {article?.publisher_name || "출처 확인 필요"}
                    </strong>
                    <span className="quiet-badge">
                      {labels[String(row.label)] || "분류 미확인"}
                    </span>
                  </div>
                  <p>{typeof row.evidence === "string" ? row.evidence : ""}</p>
                  <button
                    className="citation-button"
                    onClick={() => onCite([id])}
                  >
                    해당 기사 확인 <ArrowUpRight size={12} />
                  </button>
                </div>
              );
            })}
          {typeof payload.note === "string" && (
            <p className="small muted">{payload.note}</p>
          )}
        </>
      )}
      {Array.isArray(payload.unknowns) && payload.unknowns.length > 0 && (
        <div className="unknowns">
          <strong>함께 확인할 내용</strong>
          {payload.unknowns
            .filter((v): v is string => typeof v === "string")
            .map((value, index) => (
              <p key={index}>{value}</p>
            ))}
        </div>
      )}
      <p className="analysis-provenance">
        저장된 결과 · {output.model_version} / {output.prompt_version}
      </p>
    </div>
  );
}

export function ArticleBody({
  storyId,
  article,
}: {
  storyId: string;
  article: Story["articles"][number];
}) {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ["article-content", storyId, article.id],
    queryFn: ({ signal }) => api.articleContent(storyId, article.id, signal),
    enabled: open && apiVersion === "v2",
    retry: false,
  });
  if (apiVersion !== "v2") return null;
  return (
    <details
      className="article-body"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>{article.publisher_name} · 본문 확인</summary>
      {open &&
        (query.isPending ? (
          <p role="status">본문 공개 범위를 확인하고 있어요.</p>
        ) : query.isError ? (
          <p role="alert">
            본문을 불러오지 못했습니다. 원문 링크를 확인해주세요.
          </p>
        ) : (
          <>
            <p className="small muted">{query.data?.notice}</p>
            {query.data?.status === "available" && query.data.text && (
              <div className="licensed-body">{query.data.text}</div>
            )}
            <a
              className="citation-button"
              href={article.url}
              target="_blank"
              rel="noreferrer"
            >
              언론사 원문 열기 <ArrowUpRight size={12} />
            </a>
          </>
        ))}
    </details>
  );
}
