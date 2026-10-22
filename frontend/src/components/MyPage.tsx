import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowUpRight,
  Bookmark,
  Check,
  Settings2,
  UserRound,
  X,
} from "lucide-react";
import type { FeedItem } from "../api/types";
import type { ReaderState } from "../presentation/reading";
import { readingStats } from "../presentation/reading";
import { categoryNames } from "../presentation/timeline";
import { BalanceGauge, TopicRing, WeeklyBars } from "./ReadingCharts";

type Props = {
  reader: ReaderState;
  today: string;
  storageError: boolean;
  onPreferences: (name: string, tracking: boolean) => void;
  onClear: () => void;
  saved: FeedItem[];
  savedCount: number;
  loading: boolean;
  unavailable: number;
  onRetry: () => void;
  onOpen: (id: string) => void;
  onUnsave: (id: string) => void;
};
export function MyPage(p: Props) {
  const [settings, setSettings] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const stats = readingStats(p.reader.events, p.today);
  return (
    <div className="mypage">
      <div className="page-heading">
        <div>
          <span className="overline">MY READING JOURNEY</span>
          <h1>나의 뉴스 생활</h1>
          <p>조금 더 넓은 시야를 만드는, 매일의 기록.</p>
        </div>
        <span className="quiet-badge">이 브라우저에 저장</span>
      </div>
      <section className="profile-card">
        <div className="profile-avatar">
          <UserRound size={26} />
        </div>
        <div>
          <span className="overline">HELLO, READER</span>
          <h2>{p.reader.displayName}님, 반가워요.</h2>
          <p>
            {p.reader.trackingEnabled
              ? "나의 속도로 세상을 읽어보세요."
              : "열람 기록 수집을 일시 정지했어요."}
          </p>
        </div>
        <button
          className="icon-button"
          aria-label="내 정보 및 기록 설정"
          onClick={() => setSettings(true)}
        >
          <Settings2 size={21} />
        </button>
      </section>
      {p.storageError && (
        <p className="notice" role="alert">
          브라우저 저장소를 사용할 수 없습니다. 새로고침하면 기록이 사라질 수
          있어요.
        </p>
      )}
      <div className="dashboard-grid">
        <BalanceGauge />
        <div className="dashboard-right">
          <div className="reading-overview">
            <div>
              <span>최근 7일 열람</span>
              <strong>
                {stats.total}
                <small>건</small>
              </strong>
            </div>
            <div>
              <span>열람 사건의 출처</span>
              <strong>
                {stats.publisherCount}
                <small>곳</small>
              </strong>
            </div>
            <div>
              <span>읽은 주제</span>
              <strong>
                {stats.topicCount}
                <small>/ 4</small>
              </strong>
            </div>
          </div>
          <TopicRing stats={stats} />
        </div>
        <WeeklyBars stats={stats} today={p.today} />
      </div>
      <p className="local-record-note">
        상세 화면을 연 사건을 집계한 개인 기록이며, 실제 독서 시간이나 정치적
        성향을 의미하지 않습니다.
        {stats.demoCount > 0 &&
          ` 최근 7일 기록에 가상 뉴스 ${stats.demoCount}건이 포함되어 있습니다.`}
      </p>
      <section className="bookshelf dashboard-card">
        <div className="dashboard-card-heading">
          <div>
            <span className="overline">SAVED FOR LATER</span>
            <h2>
              다시 읽고 싶은 뉴스{" "}
              <span className="count-label">{p.savedCount}</span>
            </h2>
          </div>
          <Bookmark size={18} />
        </div>
        {p.loading ? (
          <p className="muted" role="status">
            저장한 뉴스를 불러오고 있어요.
          </p>
        ) : !p.savedCount ? (
          <div className="bookshelf-empty">
            <Bookmark size={26} />
            <h3>좋은 기사는 곁에 두세요.</h3>
            <p>뉴스 카드의 북마크를 누르면 여기에 모아드려요.</p>
          </div>
        ) : (
          p.saved.map(({ story }) => (
            <div className="saved-row" key={story.id}>
              <div>
                <span className="overline">
                  {categoryNames[story.category]}{" "}
                  {story.is_demo ? "· 가상 뉴스" : ""}
                </span>
                <button
                  className="saved-title"
                  onClick={() => p.onOpen(story.id)}
                >
                  {story.title}
                  <ArrowUpRight size={16} />
                </button>
                <span className="muted small">
                  {story.coverage.publisher_count}개 출처 ·{" "}
                  {story.coverage.article_count}개 기사
                </span>
              </div>
              <button
                className="icon-button saved"
                aria-label={`${story.title} 보관함에서 삭제`}
                onClick={() => p.onUnsave(story.id)}
              >
                <Bookmark size={18} fill="currentColor" />
              </button>
            </div>
          ))
        )}
        {p.unavailable > 0 && (
          <div className="notice" role="status">
            {p.unavailable}건을 불러오지 못했습니다.{" "}
            <button className="text-button" onClick={p.onRetry}>
              다시 시도
            </button>
          </div>
        )}
      </section>
      <Dialog.Root
        open={settings}
        onOpenChange={(value) => {
          setSettings(value);
          setConfirmClear(false);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="settings-dialog">
            <Dialog.Close
              className="icon-button dialog-close"
              aria-label="설정 닫기"
            >
              <X size={20} />
            </Dialog.Close>
            <span className="overline">READER SETTINGS</span>
            <Dialog.Title>내 정보 및 기록 설정</Dialog.Title>
            <Dialog.Description>
              로그인 계정이 아닌 이 브라우저의 프로필입니다. 다른 기기와
              동기화되지 않습니다.
            </Dialog.Description>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                const values = new FormData(event.currentTarget);
                p.onPreferences(
                  String(values.get("name") || ""),
                  values.has("tracking"),
                );
                setSettings(false);
              }}
            >
              <label>
                표시 이름
                <input
                  name="name"
                  maxLength={20}
                  defaultValue={p.reader.displayName}
                  autoComplete="nickname"
                />
              </label>
              <label className="checkbox-label">
                <input
                  name="tracking"
                  type="checkbox"
                  defaultChecked={p.reader.trackingEnabled}
                />
                뉴스 열람 기록 저장
              </label>
              <p className="small muted">
                끄면 새 열람을 기록하지 않습니다. 기존 기록은 유지됩니다.
              </p>
              <button className="button" type="submit">
                <Check size={16} />
                설정 저장
              </button>
            </form>
            <div className="clear-history">
              <p>열람 기록만 삭제하며, 보관함은 유지합니다.</p>
              {confirmClear ? (
                <div>
                  <span>열람 기록을 모두 지울까요?</span>
                  <button
                    className="text-button"
                    onClick={() => {
                      p.onClear();
                      setConfirmClear(false);
                    }}
                  >
                    기록 삭제 확인
                  </button>
                  <button onClick={() => setConfirmClear(false)}>취소</button>
                </div>
              ) : (
                <button
                  className="text-button"
                  onClick={() => setConfirmClear(true)}
                >
                  열람 기록 삭제
                </button>
              )}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
