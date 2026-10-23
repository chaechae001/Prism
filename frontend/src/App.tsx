import { useEffect, useState } from "react";
import {
  Bookmark,
  ChevronDown,
  Grid2X2,
  Home,
  Search,
  Send,
  Settings2,
  UserRound,
  X,
  Moon,
  Sun,
} from "lucide-react";
import { apiMode, apiVersion } from "./api/client";
import type { Category, Mode, Scenario } from "./api/types";
import { ConnectionStatus } from "./components/ConnectionStatus";
import { StoryDetail } from "./components/StoryDetail";
import { NewsComments } from "./features/comments/NewsComments";
import { NewsInbox } from "./features/news-chat/NewsInbox";
import { useSocialWorkspace } from "./hooks/useSocialWorkspace";
import { useTheme } from "./hooks/useTheme";
import { SocialPost } from "./components/SocialPost";
import { NewsPhoto } from "./components/NewsPhoto";
import { NewsReel } from "./components/NewsReel";
import { isLocalClusterStory } from "./presentation/clusterPreview";
import { useNewsWorkspace } from "./hooks/useNewsWorkspace";
import { useReaderActivity } from "./hooks/useReaderActivity";
import {
  categoryNames,
  dateKey,
  selectStoryReel,
  dayLabel,
  type DetailTab,
  type View,
} from "./presentation/timeline";
import "./social.css";
import "./social-features.css";

const navigation = [
  { id: "timeline", label: "홈", icon: Home },
  { id: "categories", label: "카테고리", icon: Grid2X2 },
  { id: "chat", label: "AI 대화", icon: Send },
  { id: "briefing", label: "사진 탐색", icon: Search },
  { id: "mypage", label: "내 정보", icon: UserRound },
] as const;

export function App() {
  const w = useNewsWorkspace();
  const activity = useReaderActivity();
  const social = useSocialWorkspace();
  const { theme, toggleTheme } = useTheme();
  const [commentStory, setCommentStory] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const [draft, setDraft] = useState(w.q);
  const [settings, setSettings] = useState(false);
  const [reel, setReel] = useState<string | null>(null);
  useEffect(() => setDraft(w.q), [w.q]);
  useEffect(() => {
    window.scrollTo({ top: 0 });
    setReel(null);
  }, [w.view]);
  const navigate = (view: View) =>
    w.update({
      view: view === "timeline" ? null : view,
      q: null,
      category: null,
      date: null,
      from: null,
      to: null,
      story: null,
      panel: null,
      dm: null,
    });
  const open = (id: string, tab: DetailTab = "summary") =>
    w.update({ story: id, panel: tab === "summary" ? null : tab });
  const today = dateKey(new Date().toISOString());
  const { stories: reelStories, initial: reelInitial } = selectStoryReel(
    w.items, reel, w.eventDates,
  );
  const openDm = (story: (typeof w.items)[number]["story"]) => {
    social.openThread(story);
    w.update({
      view: "chat",
      dm: story.id,
      story: null,
      panel: null,
      date: null,
      from: null,
      to: null,
      q: null,
      category: null,
    });
  };
  const latest = [...w.items]
    .sort(
      (a, b) => Date.parse(b.story.updated_at) - Date.parse(a.story.updated_at),
    )
    .slice(0, 10)
    .map((i) => i.story);
  const isMock = w.feed.data?.pages[0]?.meta.is_mock ?? apiMode === "mock";
  const dbCluster = w.feed.data?.pages[0]?.meta.policy_version === "cluster-db-v1";
  const clusterPreview = dbCluster || w.feed.data?.pages[0]?.meta.policy_version === "cluster-local-v1"
    || w.items.some(({ story }) => isLocalClusterStory(story));
  const title =
    w.view === "mypage"
      ? "내 정보"
      : w.view === "chat"
        ? "AI 대화"
        : w.view === "categories"
          ? "카테고리"
          : w.view === "briefing"
            ? "탐색"
            : "prism";
  const retry = () => {
    void (w.view === "mypage" ? w.savedQuery.refetch() : w.feed.refetch());
  };

  return (
    <div className="social-app">
      <a className="skip-link" href="#social-main">
        본문 바로가기
      </a>
      <aside className="social-sidebar">
        <button
          className="social-wordmark"
          onClick={() => navigate("timeline")}
        >
          prism<span>·</span>
        </button>
        <nav aria-label="데스크톱 메뉴">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={w.view === id ? "active" : ""}
              onClick={() => navigate(id)}
              aria-current={w.view === id ? "page" : undefined}
            >
              <Icon size={25} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <button
          className="sidebar-settings"
          onClick={() => setSettings((v) => !v)}
        >
          <Settings2 size={23} />
          연결 및 피드 설정
        </button>
      </aside>
      <div className="social-layout">
        <section className="social-column">
          <header className="social-header">
            <button
              className={
                w.view === "timeline" ? "social-wordmark" : "social-page-title"
              }
              onClick={() => navigate("timeline")}
            >
              {title}
              {w.view === "timeline" && (
                <>
                  <span>·</span>
                  <ChevronDown size={16} />
                </>
              )}
            </button>
            <div>
              <button
                className="social-icon"
                aria-label={
                  theme === "dark" ? "라이트 모드로 변경" : "다크 모드로 변경"
                }
                onClick={toggleTheme}
              >
                {theme === "dark" ? <Sun size={22} /> : <Moon size={22} />}
              </button>
              <button
                className="social-icon"
                aria-label="AI 대화 열기"
                onClick={() => navigate("chat")}
              >
                <Send size={24} />
              </button>
            </div>
          </header>
          <main id="social-main">
            {clusterPreview && (
              <section className="cluster-preview-notice" aria-label="군집분석 결과 안내">
                <strong>군집분석 결과 · 동일 사건 검토 전</strong>
                <span>{w.feed.data?.pages[0]?.meta.policy_notes[0] || "저장한 군집 대표기사와 관련 기사를 표시합니다."}</span>
                <small>{dbCluster ? "DB 군집 결과를 60초마다 확인합니다. 대표기사와 원문 출처를 제공하며 AI 요약은 생성하지 않았습니다." : "대표기사 본문 앞부분과 관련 기사를 표시합니다. AI 요약은 생성하지 않았습니다."}</small>
              </section>
            )}
            {w.view === "timeline" && (
              <>
                <div className="social-feed-heading">
                  <span>여러 시선, 하나의 이야기.</span>
                  <span>기사별 뉴스 스토리</span>
                </div>
                {latest.length > 0 && (
                  <section
                    className="news-stories"
                    aria-label="최근 뉴스 스토리"
                  >
                    {latest.map((story) => (
                      <button
                        className="news-story"
                        key={story.id}
                        onClick={() => setReel(story.id)}
                        aria-label={`${story.title} 스토리 보기`}
                      >
                        <span className="story-ring">
                          <NewsPhoto story={story} compact />
                        </span>
                        <small className="story-date">
                          {dayLabel(w.eventDates[story.id] || dateKey(story.updated_at), {
                            month: "numeric", day: "numeric",
                          })}
                        </small>
                        <span>
                          {story.title}
                        </span>
                      </button>
                    ))}
                  </section>
                )}
                <div className="feed-switch">
                  <span>
                    최근 뉴스 <ChevronDown size={13} />
                  </span>
                  <small>
                    {clusterPreview ? "군집 결과 · 검토 전" : isMock ? "DEMO · 가상 뉴스" : "출처와 함께 읽기"}
                  </small>
                </div>
              </>
            )}
            {w.view === "categories" && (
              <section className="category-intro">
                <h1>주제별 뉴스</h1>
                <p>여러 시선, 하나의 이야기.</p>
                <div className="social-categories">
                  {(
                    ["", ...Object.keys(categoryNames)] as (Category | "")[]
                  ).map((c) => (
                    <button
                      key={c}
                      aria-pressed={w.category === c}
                      className={w.category === c ? "active" : ""}
                      onClick={() => w.update({ category: c || null })}
                    >
                      {c ? categoryNames[c] : "전체"}
                    </button>
                  ))}
                </div>
              </section>
            )}
            {w.view === "briefing" && (
              <section className="explore-heading">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    w.update({ q: draft.trim() || null });
                  }}
                >
                  <Search size={19} />
                  <input
                    aria-label="뉴스 검색"
                    placeholder="관심 있는 뉴스 검색"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    maxLength={100}
                  />
                  <button type="submit">검색</button>
                </form>
                <p>
                  사진으로 발견하는 새로운 이야기{" "}
                  {isMock && <span>· 예시 사진</span>}
                </p>
              </section>
            )}
            {w.view === "mypage" && (
              <section className="social-profile">
                <div className="profile-identity">
                  <span className="profile-avatar">
                    <UserRound size={34} />
                  </span>
                  <div>
                    <h1>나의 뉴스 서랍</h1>
                    <p>
                      <strong>{w.saved.length}</strong> 저장한 뉴스
                    </p>
                  </div>
                  <Bookmark size={22} />
                </div>
                <p>다시 읽고 싶은 이야기를 모아두세요.</p>
                <small>
                  북마크는 현재 브라우저에 저장됩니다.
                  <br />
                  프로필 설정과 독서 통계는 추후 추가 예정입니다.
                </small>
                <div className="profile-grid-tab">
                  <Grid2X2 size={16} /> 저장한 기사
                </div>
                {w.savedQuery.data?.unavailable ? (
                  <p role="status">
                    저장한 기사 {w.savedQuery.data.unavailable}건을 불러오지
                    못했습니다. <button onClick={retry}>다시 시도</button>
                  </p>
                ) : null}
              </section>
            )}
            {(w.storageError || social.storageError) && (
              <p className="social-notice" role="alert">
                브라우저 저장 공간에 접근할 수 없어 북마크·댓글·대화 기록을
                유지하지 못했습니다.
              </p>
            )}
            {w.view === "chat" ? (
              <NewsInbox
                key={w.dm || "inbox"}
                social={social}
                selected={w.dm}
                onSelect={(id) => w.update({ dm: id })}
                onBack={() => w.update({ dm: null })}
                onOpen={(id) => open(id)}
              />
            ) : (
              <>
                {w.loading ? (
                  <div className="social-loading" role="status">
                    뉴스를 불러오는 중입니다…
                    <div />
                    <div />
                  </div>
                ) : w.error ? (
                  <section className="social-empty" role="alert">
                    <h2>뉴스를 불러오지 못했어요.</h2>
                    <p>
                      {w.error instanceof Error
                        ? w.error.message
                        : "연결 상태를 확인해주세요."}
                    </p>
                    <button className="social-primary" onClick={retry}>
                      다시 시도
                    </button>
                  </section>
                ) : w.displayed.length === 0 ? (
                  <section className="social-empty">
                    <Bookmark size={32} />
                    <h2>
                      {w.view === "mypage"
                        ? "아직 저장한 뉴스가 없어요."
                        : "조건에 맞는 뉴스가 없어요."}
                    </h2>
                    <p>
                      {w.view === "mypage"
                        ? "기사 아래 북마크를 눌러 여기에 모아보세요."
                        : "다른 날짜나 검색어로 살펴보세요."}
                    </p>
                    <button
                      className="social-primary"
                      onClick={() => navigate("timeline")}
                    >
                      전체 뉴스 보기
                    </button>
                  </section>
                ) : w.view === "briefing" || w.view === "mypage" ? (
                  <div className="social-photo-grid">
                    {w.displayed.map(({ story }) => (
                      <button
                        key={story.id}
                        onClick={() => open(story.id)}
                        aria-label={`${story.title} 상세 보기`}
                      >
                        <NewsPhoto story={story} compact />
                        {w.view === "mypage" && (
                          <Bookmark size={15} fill="currentColor" />
                        )}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="social-feed">
                    {w.displayed.map((item) => (
                      <SocialPost
                        key={item.story.id}
                        item={item}
                        clusterPreview={clusterPreview}
                        saved={w.saved.includes(item.story.id)}
                        onSave={() => w.toggleSave(item.story.id)}
                        onOpen={(tab) => open(item.story.id, tab)}
                        onComments={() =>
                          setCommentStory({
                            id: item.story.id,
                            title: item.story.title,
                          })
                        }
                        onDm={() => openDm(item.story)}
                        commentCount={
                          social.comments.filter(
                            (c) => c.storyId === item.story.id,
                          ).length
                        }
                      />
                    ))}
                  </div>
                )}
                {w.view !== "mypage" && w.feed.hasNextPage && (
                  <button
                    className="social-load-more"
                    disabled={w.feed.isFetchingNextPage}
                    onClick={() => void w.feed.fetchNextPage()}
                  >
                    {w.feed.isFetchingNextPage
                      ? "불러오는 중…"
                      : "뉴스 더 보기"}
                  </button>
                )}
              </>
            )}
            {settings && (
              <section className="social-settings">
                <button
                  className="social-icon settings-close"
                  aria-label="피드 설정 닫기"
                  onClick={() => setSettings(false)}
                >
                  <X size={18} />
                </button>
                <h2>피드 및 개발 연결 설정</h2>
                {apiVersion === "v1" && (
                  <>
                    <label>
                      추천 방식
                      <select
                        value={w.mode}
                        onChange={(e) =>
                          w.update({ mode: e.target.value as Mode })
                        }
                      >
                        <option value="balanced">균형 있게</option>
                        <option value="latest">최신순</option>
                        <option value="explore">새로운 주제</option>
                      </select>
                    </label>
                    <label>
                      다양성 {w.diversity}%
                      <input
                        type="range"
                        min="0"
                        max="100"
                        value={w.diversity}
                        onChange={(e) =>
                          w.update({ diversity: e.target.value })
                        }
                      />
                    </label>
                  </>
                )}
                {apiMode === "mock" && (
                  <label>
                    Mock 상태
                    <select
                      value={w.scenario}
                      onChange={(e) =>
                        w.setScenario(e.target.value as Scenario)
                      }
                    >
                      <option value="normal">정상</option>
                      <option value="slow">로딩</option>
                      <option value="empty">빈 목록</option>
                      <option value="error">오류</option>
                    </select>
                  </label>
                )}
                <ConnectionStatus meta={w.feed.data?.pages[0]?.meta} />
              </section>
            )}
          </main>
          <footer className="social-footer">
            prism · 다양한 출처를 연결하는 뉴스
          </footer>
        </section>
        <aside className="social-right">
          <div className="right-profile">
            <span className="post-avatar">p·</span>
            <div>
              <strong>prism.news</strong>
              <small>다른 시선이 만나는 곳</small>
            </div>
            <button onClick={() => navigate("mypage")}>저장 목록</button>
          </div>
          <div className="right-heading">
            <strong>지금 주목할 이야기</strong>
            <span>최근 뉴스</span>
          </div>
          {latest.slice(0, 4).map((story) => (
            <button
              className="right-news"
              key={story.id}
              onClick={() => open(story.id)}
            >
              <NewsPhoto story={story} compact />
              <span>
                <small>{categoryNames[story.category]}</small>
                <strong>{story.title}</strong>
              </span>
            </button>
          ))}
          <div className="right-note">
            하나의 사건, 여러 매체의 시선.
            <br />
            기사의 출처를 확인하고 맥락을 읽어보세요.
            <p>
              소개 · 출처 · 뉴스 읽기 안내
              <br />© {today.slice(0, 4)} PRISM
            </p>
          </div>
          <button
            className="settings-link"
            onClick={() => setSettings((v) => !v)}
          >
            연결 및 피드 설정
          </button>
        </aside>
      </div>
      <nav className="social-bottom" aria-label="하단 메뉴">
        {navigation.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => navigate(id)}
            aria-label={label}
            aria-current={w.view === id ? "page" : undefined}
            className={w.view === id ? "active" : ""}
          >
            {id === "mypage" ? (
              <span className="nav-profile">
                <Icon size={20} />
              </span>
            ) : (
              <Icon size={26} strokeWidth={w.view === id ? 2.5 : 1.65} />
            )}
            <span className="sr-only">{label}</span>
          </button>
        ))}
      </nav>
      <button
        className="mobile-settings"
        aria-label="연결 및 피드 설정"
        onClick={() => setSettings((v) => !v)}
      >
        <Settings2 size={16} />
      </button>
      {reel !== null && reelStories.length > 0 && (
        <NewsReel
          key={`${reel}-${reelStories.map((s) => s.id).join()}`}
          stories={reelStories}
          initial={reelInitial}
          onClose={() => setReel(null)}
          onOpen={(id) => open(id)}
          saved={w.saved}
          onSave={w.toggleSave}
        />
      )}
      {commentStory && (
        <NewsComments
          key={commentStory.id}
          storyId={commentStory.id}
          title={commentStory.title}
          comments={social.comments}
          onClose={() => setCommentStory(null)}
          onAdd={social.addComment}
          onRemove={social.removeComment}
        />
      )}
      {w.selected && (
        <StoryDetail
          key={w.selected + w.detailTab}
          id={w.selected}
          clusterPreview={clusterPreview}
          initialTab={w.detailTab}
          onClose={() => w.update({ story: null, panel: null })}
          saved={w.saved.includes(w.selected)}
          onSave={w.toggleSave}
          onRead={activity.recordRead}
        />
      )}
    </div>
  );
}
