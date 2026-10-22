import type { FeedItem } from "../api/types";

export const categoryNames = {
  politics: "정치",
  economy: "경제",
  society: "사회",
  technology: "기술",
};
export type View = "timeline" | "briefing" | "categories" | "mypage" | "chat";
export type DetailTab =
  "summary" | "perspectives" | "sources" | "five_w" | "easy" | "sentiment";
export const referenceDate = "2026-10-21";

export function dateKey(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "";
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function validDay(value: string): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(`${value}T00:00:00Z`)) &&
    new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value
  );
}

export function moveDay(value: string, amount: number): string {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + amount);
  return date.toISOString().slice(0, 10);
}

export function dayLabel(
  value: string,
  options: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    ...options,
  }).format(new Date(`${value}T00:00:00+09:00`));
}

export function visibleItems(
  items: FeedItem[],
  day: string,
  from: string,
  to: string,
): FeedItem[] {
  return items.filter(({ story }) => {
    const key = dateKey(story.updated_at);
    return (
      (!day || key === day) && (!from || key >= from) && (!to || key <= to)
    );
  });
}

export function groupTimeline(
  items: FeedItem[],
  eventDates: Record<string, string> = {},
): { day: string; items: FeedItem[] }[] {
  const groups = new Map<string, FeedItem[]>();
  for (const item of items) {
    const key = eventDates[item.story.id] || dateKey(item.story.updated_at);
    if (!key) continue;
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  return [...groups]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([day, entries]) => ({ day, items: entries }));
}

export function weekDays(anchor: string, offset: number): string[] {
  return Array.from({ length: 7 }, (_, index) =>
    moveDay(anchor, offset * 7 - 6 + index),
  );
}
