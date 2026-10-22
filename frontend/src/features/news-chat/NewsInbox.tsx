import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowUpRight,
  MessageCircle,
  Send,
  Sparkles,
} from "lucide-react";
import { api } from "../../api/client";
import { socialRequest, type ChatReply, type ChatStatus } from "../../api/social";
import { categoryNames } from "../../presentation/timeline";
import type { useSocialWorkspace } from "../../hooks/useSocialWorkspace";
type Social = ReturnType<typeof useSocialWorkspace>;
export function NewsInbox({
  social,
  selected,
  onSelect,
  onBack,
  onOpen,
}: {
  social: Social;
  selected: string | null;
  onSelect: (id: string) => void;
  onBack: () => void;
  onOpen: (id: string) => void;
}) {
  const thread = social.threads.find((t) => t.id === selected);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const controller = useRef<AbortController | null>(null);
  const story = useQuery({
    queryKey: ["story", thread?.id],
    queryFn: ({ signal }) => api.story(thread!.id, signal),
    enabled: !!thread,
    retry: false,
  });
  const status = useQuery({
    queryKey: ["social-chat-status"],
    queryFn: ({ signal }) =>
      socialRequest<ChatStatus>("/chat/status", {
        signal,
      }),
    retry: false,
    staleTime: 10000,
  });
  useEffect(() => {
    setDraft("");
    setError("");
    return () => {
      controller.current?.abort();
      inFlight.current = false;
    };
  }, [selected]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end", behavior: "instant" });
  }, [thread?.messages.length, busy]);
  async function send(text = draft) {
    const question = text.trim();
    if (!thread || !question || inFlight.current) return;
    if (story.isPending || story.isError) {
      setError("기사를 불러온 뒤 다시 시도해주세요.");
      return;
    }
    if (!status.data?.configured) {
      setError(
        status.data?.notice ||
          "LLM 연결 상태를 확인할 수 없습니다. 서버 설정을 확인해주세요.",
      );
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError("");
    setDraft("");
    const id = thread.id;
    const last = thread.messages.at(-1);
    const retrying = last?.role === "user" && last.text === question;
    if (!retrying) social.append(id, { role: "user", text: question });
    const abort = new AbortController();
    controller.current = abort;
    try {
      const reply = await socialRequest<ChatReply>(
        `/stories/${encodeURIComponent(id)}/chat`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            history: (retrying ? thread.messages.slice(0, -1) : thread.messages)
              .slice(-10)
              .map((m) => ({ role: m.role, content: m.text.slice(0, 5000) })),
          }),
          signal: abort.signal,
        },
      );
      if (!abort.signal.aborted)
        social.append(id, {
          role: "assistant",
          text: reply.answer,
          articleIds: reply.article_ids,
          model: reply.model,
        });
    } catch (e) {
      if (!abort.signal.aborted) {
        setError(e instanceof Error ? e.message : "답변을 받지 못했습니다.");
        setDraft(question);
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  if (!thread)
    return (
      <section className="news-inbox">
        <header>
          <h1>
            메시지 <span>{social.threads.length}</span>
          </h1>
          <span className="social-kicker">NEWS DM</span>
        </header>
        <p className="inbox-hint">
          게시물의 종이비행기를 누르면 뉴스 대화가 시작됩니다.
        </p>
        {social.threads.length ? (
          <div className="inbox-list">
            {social.threads.map((t) => (
              <button key={t.id} onClick={() => onSelect(t.id)}>
                <span className={`dm-avatar dm-${t.category}`}>
                  {categoryNames[t.category].slice(0, 1)}
                </span>
                <span>
                  <strong>{t.title}</strong>
                  <small>
                    {t.messages.at(-1)?.text ||
                      "이 뉴스에 대해 무엇이든 물어보세요."}
                  </small>
                </span>
                <MessageCircle size={18} />
              </button>
            ))}
          </div>
        ) : (
          <div className="inbox-empty">
            <Send size={40} />
            <h2>아직 뉴스 대화가 없어요.</h2>
            <p>홈에서 궁금한 뉴스의 DM 아이콘을 눌러보세요.</p>
          </div>
        )}
        <p className="local-only-note">
          대화 목록과 기록은 이 브라우저에 저장됩니다.
        </p>
      </section>
    );
  return (
    <section className="news-conversation">
      <header>
        <button
          className="social-icon"
          onClick={onBack}
          aria-label="메시지 목록으로"
        >
          <ArrowLeft />
        </button>
        <span className={`dm-avatar dm-${thread.category}`}>
          {categoryNames[thread.category].slice(0, 1)}
        </span>
        <div>
          <strong>{thread.title}</strong>
          <small>PRISM AI · {categoryNames[thread.category]} 뉴스 전용</small>
        </div>
      </header>
      <div className="conversation-scroll">
        <div className="conversation-profile">
          <span className={`dm-avatar dm-${thread.category}`}>
            {categoryNames[thread.category].slice(0, 1)}
          </span>
          <h2>{thread.title}</h2>
          <p>선택한 뉴스에 관해서만 대화합니다.</p>
          <button onClick={() => onOpen(thread.id)}>
            뉴스 게시물 보기 <ArrowUpRight size={13} />
          </button>
        </div>
        <p className="chat-context-note">
          {story.data?.story.is_demo ? "가상 뉴스 · " : ""}현재 제목·제공된
          요약·관련 기사 정보를 참고합니다. 원문 전문은 아직 연결되지
          않았습니다.
        </p>
        {status.isPending ? (
          <p className="chat-context-note">AI 연결 확인 중…</p>
        ) : !status.data?.configured ? (
          <p className="chat-config-notice" role="status">
            {status.data?.notice || "AI 서버에 연결하지 못했습니다."}
            <button onClick={() => void status.refetch()}>
              연결 다시 확인
            </button>
          </p>
        ) : null}
        {story.isError && (
          <p role="alert">
            뉴스를 불러오지 못했습니다.{" "}
            <button onClick={() => void story.refetch()}>다시 시도</button>
          </p>
        )}
        {!thread.messages.length && (
          <div className="conversation-prompts">
            {[
              "이 기사를 세 줄로 요약해줘",
              "초등학생도 이해할 수 있게 설명해줘",
              "이 기사에서 확인된 사실은 무엇이야?",
            ].map((p) => (
              <button key={p} disabled={busy} onClick={() => void send(p)}>
                <Sparkles size={14} />
                {p}
              </button>
            ))}
          </div>
        )}
        <div className="message-list" aria-live="polite">
          {thread.messages.map((m) => (
            <div className={`message-bubble ${m.role}`} key={m.id}>
              <p>{m.text}</p>
              {m.role === "assistant" && (
                <small>
                  AI 답변 ·{" "}
                  {m.articleIds?.length ? "기사 근거 포함" : "제공 정보 범위"} ·
                  정확성 확인 필요
                </small>
              )}
            </div>
          ))}
          {busy && (
            <div className="message-bubble assistant" role="status">
              기사 내용을 살펴보고 있어요…
            </div>
          )}
        </div>
        {error && (
          <p className="chat-error" role="alert">
            {error}
          </p>
        )}
        <div ref={end} />
      </div>
      <form
        className="dm-composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          aria-label="뉴스에 대해 질문하기"
          placeholder="메시지 입력…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={busy}
          maxLength={2000}
        />
        <button
          type="submit"
          disabled={!draft.trim() || busy}
          aria-label="메시지 보내기"
        >
          <Send size={20} />
        </button>
      </form>
      <p className="local-only-note dm-disclosure">
        전송 시 질문·최근 대화·이 뉴스의 제공 정보를 LLM으로 전달합니다.
      </p>
    </section>
  );
}
