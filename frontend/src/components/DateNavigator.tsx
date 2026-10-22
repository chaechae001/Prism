import * as Dialog from "@radix-ui/react-dialog";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  RotateCcw,
  X,
} from "lucide-react";
import { useState } from "react";
import { dayLabel, validDay, weekDays } from "../presentation/timeline";

type Props = {
  serverDates?: boolean;
  anchor: string;
  selected: string;
  from: string;
  to: string;
  counts: Map<string, number>;
  onDay: (day: string) => void;
  onRange: (from: string, to: string) => void;
  onClear: () => void;
};
export function DateNavigator({
  serverDates = false,
  anchor,
  selected,
  from,
  to,
  counts,
  onDay,
  onRange,
  onClear,
}: Props) {
  const [week, setWeek] = useState(0);
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState(from || selected || anchor);
  const [end, setEnd] = useState(to || selected || anchor);
  const [error, setError] = useState("");
  const days = weekDays(anchor, week);
  const resetRange = () => {
    setStart(from || selected || anchor);
    setEnd(to || selected || anchor);
    setError("");
    setOpen(true);
  };
  return (
    <section className="date-navigator" aria-label="날짜별 뉴스 탐색">
      <div className="calendar-heading">
        <div>
          <CalendarDays size={17} />
          <h2>{dayLabel(days[6], { year: "numeric", month: "long" })}</h2>
          <button
            className="calendar-step"
            aria-label="이전 7일"
            onClick={() => setWeek((v) => v - 1)}
          >
            <ChevronLeft size={15} />
          </button>
          <button
            className="calendar-step"
            aria-label="다음 7일"
            onClick={() => setWeek((v) => v + 1)}
          >
            <ChevronRight size={15} />
          </button>
        </div>
        <div>
          <button className="date-range-button" onClick={resetRange}>
            <CalendarDays size={13} />
            <span>기간 선택</span>
          </button>
          <button
            className={`all-dates ${!selected && !from && !to ? "active" : ""}`}
            aria-pressed={!selected && !from && !to}
            onClick={onClear}
          >
            전체
          </button>
        </div>
      </div>
      <div className="day-strip">
        {days.map((day) => {
          const active = day === selected;
          const count = counts.get(day) || 0;
          return (
            <button
              className={`day-chip ${active ? "active" : ""} ${day === anchor ? "reference-day" : ""}`}
              key={day}
              aria-label={`${day} 뉴스 ${count}개`}
              aria-pressed={active}
              onClick={() => onDay(day)}
            >
              <span>{dayLabel(day, { weekday: "short" })}</span>
              <strong>{day.slice(-2)}</strong>
              <i className={count ? "has-stories" : ""} />
              <small>
                {day === anchor ? "최근" : count ? `${count}건` : ""}
              </small>
            </button>
          );
        })}
      </div>
      {(selected || from || to) && (
        <div className="date-filter-note">
          <span>
            {selected || `${from || "처음"} ~ ${to || "마지막"}`} ·{" "}
            {serverDates
              ? "사건의 최초 기사 날짜(KST)"
              : "불러온 뉴스의 업데이트 날짜 기준"}
          </span>
          <button onClick={onClear} aria-label="날짜 필터 해제">
            <RotateCcw size={12} />
            해제
          </button>
        </div>
      )}
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="date-dialog">
            <Dialog.Close
              className="icon-button dialog-close"
              aria-label="기간 선택 닫기"
            >
              <X size={18} />
            </Dialog.Close>
            <div className="dialog-eyebrow">NEWS ARCHIVE</div>
            <Dialog.Title>어느 날의 뉴스가 궁금하세요?</Dialog.Title>
            <Dialog.Description>
              {serverDates
                ? "서버의 게시된 사건 전체를 한국 시간 기준 사건 날짜로 조회합니다."
                : "현재 불러온 뉴스에서 업데이트 날짜로 찾아봅니다. 서버 전체 기간 검색은 추후 연결 예정입니다."}
            </Dialog.Description>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                const values = new FormData(event.currentTarget);
                const from = String(values.get("from") || "");
                const to = String(values.get("to") || "");
                if (!validDay(from) || !validDay(to) || from > to) {
                  setError("시작일과 종료일을 올바르게 선택해주세요.");
                  return;
                }
                onRange(from, to);
                setOpen(false);
              }}
            >
              <label>
                시작일
                <input type="date" name="from" required defaultValue={start} />
              </label>
              <label>
                종료일
                <input type="date" name="to" required defaultValue={end} />
              </label>
              {error && (
                <p role="alert" className="form-error">
                  {error}
                </p>
              )}
              <button className="button" type="submit">
                선택한 기간 살펴보기
              </button>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}
