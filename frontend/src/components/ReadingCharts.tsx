import { useState } from "react";
import { ArrowUpRight, Info } from "lucide-react";
import { categoryNames, dayLabel } from "../presentation/timeline";
import type { readingStats } from "../presentation/reading";

type Stats = ReturnType<typeof readingStats>;
const colors = ["#564565", "#9c8cab", "#adbd8a", "#caa69c"];

export function BalanceGauge() {
  const [example, setExample] = useState(false);
  const score: number | null = example ? 82 : null;
  const circumference = 2 * Math.PI * 91;
  return (
    <section className="dashboard-card balance-card">
      <div className="dashboard-card-heading">
        <div>
          <span className="overline">READING BALANCE</span>
          <h2>나의 밸런스 스코어</h2>
        </div>
        <span className="quiet-badge">
          {example ? "디자인 예시" : "평가 준비 중"}
        </span>
      </div>
      <div
        className={`balance-gauge ${example ? "is-example" : ""}`}
        role="img"
        aria-label={
          score === null
            ? "밸런스 스코어: 평가 모델 미연결, 점수 없음. 범위 0에서 100."
            : "디자인 예시 82점. 실제 사용자 분석 결과가 아닙니다."
        }
      >
        <svg viewBox="0 0 240 240" aria-hidden="true">
          <circle className="gauge-outer" cx="120" cy="120" r="107" />
          <circle className="gauge-track" cx="120" cy="120" r="91" />
          {score !== null && (
            <circle
              className="gauge-value"
              cx="120"
              cy="120"
              r="91"
              strokeDasharray={`${(circumference * score) / 100} ${circumference}`}
              transform="rotate(-90 120 120)"
            />
          )}
        </svg>
        <div className="gauge-center">
          <span>{example ? "EXAMPLE SCORE" : "BALANCE SCORE"}</span>
          <strong>
            {score === null ? "—" : score}
            <small>{score === null ? "" : "/ 100"}</small>
          </strong>
          <p>
            {example
              ? "실제 분석 결과가 아닙니다"
              : "평가 모델을 준비하고 있어요"}
          </p>
        </div>
        <span className="gauge-min">0</span>
        <span className="gauge-max">100</span>
      </div>
      <p className="balance-explanation">
        <Info size={13} />
        <span>
          열람 주제와 출처 수만으로 정치적 편향이나 완벽한 균형을 판단하지
          않습니다. 검증된 산출 기준 연결 후 점수를 제공합니다.
        </span>
      </p>
      <button
        className="example-toggle"
        aria-pressed={example}
        onClick={() => setExample((value) => !value)}
      >
        {example ? "평가 준비 상태로 돌아가기" : "점수 게이지 디자인 예시 보기"}
        <ArrowUpRight size={13} />
      </button>
    </section>
  );
}

export function TopicRing({ stats }: { stats: Stats }) {
  const radius = 61;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <section className="dashboard-card topic-ring-card">
      <div className="dashboard-card-heading">
        <div>
          <span className="overline">TOPIC MIX</span>
          <h2>어떤 주제를 읽었나요?</h2>
        </div>
        <span className="quiet-badge">최근 7일</span>
      </div>
      <div className="topic-ring-layout">
        <div
          className="topic-ring"
          role="img"
          aria-label={`최근 7일 주제별 열람. ${stats.topics.map((topic) => `${categoryNames[topic.category]} ${topic.count}건`).join(", ")}`}
        >
          <svg viewBox="0 0 160 160" aria-hidden="true">
            <circle
              cx="80"
              cy="80"
              r={radius}
              fill="none"
              stroke="#eeece7"
              strokeWidth="17"
            />
            {stats.topics.map((topic, index) => {
              const length = stats.total
                ? (circumference * topic.count) / stats.total
                : 0;
              const start = offset;
              offset += length;
              return (
                <circle
                  key={topic.category}
                  cx="80"
                  cy="80"
                  r={radius}
                  fill="none"
                  stroke={colors[index]}
                  strokeWidth="17"
                  strokeDasharray={`${Math.max(0, length - (length ? 3 : 0))} ${circumference}`}
                  strokeDashoffset={-start}
                  transform="rotate(-90 80 80)"
                />
              );
            })}
          </svg>
          <div>
            <strong>
              {stats.topicCount}
              <small>/ 4</small>
            </strong>
            <span>읽은 주제</span>
          </div>
        </div>
        <ul className="topic-ring-legend">
          {stats.topics.map((topic, index) => (
            <li key={topic.category}>
              <i style={{ background: colors[index] }} />
              <span>{categoryNames[topic.category]}</span>
              <strong>
                {topic.count}
                <small>건</small>
              </strong>
            </li>
          ))}
        </ul>
      </div>
      <p className="chart-note">
        {stats.total
          ? "주제 분포는 상세 화면을 연 사건 수를 기준으로 합니다."
          : "뉴스 상세를 열면 첫 독서 기록이 여기에 쌓입니다."}
      </p>
    </section>
  );
}

export function WeeklyBars({ stats, today }: { stats: Stats; today: string }) {
  const max = Math.max(1, ...stats.days.map((day) => day.count));
  return (
    <section className="dashboard-card weekly-card">
      <div className="dashboard-card-heading">
        <div>
          <span className="overline">WEEKLY RHYTHM</span>
          <h2>하루에 한 번, 세상을 읽는 시간</h2>
        </div>
        <span className="quiet-badge">최근 7일</span>
      </div>
      <div className="weekly-summary">
        <strong>
          {stats.total}
          <small>건</small>
        </strong>
        <span>상세 화면을 연 사건</span>
      </div>
      <div
        className="weekly-bars"
        role="img"
        aria-label={`최근 7일 열람 기록. ${stats.days.map((day) => `${day.day} ${day.count}건`).join(", ")}`}
      >
        {stats.days.map((day) => (
          <div
            className={`weekday ${day.day === today ? "is-today" : ""}`}
            key={day.day}
          >
            <span className="weekday-count">{day.count}</span>
            <div className="weekday-track">
              <span
                style={{
                  height: `${day.count ? Math.max(8, (day.count / max) * 100) : 3}%`,
                }}
              />
            </div>
            <span className="weekday-label">
              {dayLabel(day.day, { weekday: "short" })}
            </span>
            <small>{day.day.slice(5).replace("-", ".")}</small>
          </div>
        ))}
      </div>
      <p className="chart-note">
        한국 시간 기준 · 같은 사건은 하루에 한 번 집계합니다.
      </p>
    </section>
  );
}
