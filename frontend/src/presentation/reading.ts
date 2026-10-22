import type { Category, Story } from "../api/types";
import { dateKey, moveDay } from "./timeline";

export type ReadEvent = {
  storyId: string;
  title: string;
  category: Category;
  publisherIds: string[];
  readAt: string;
  isDemo: boolean;
};
export type ReaderState = {
  version: 1;
  displayName: string;
  trackingEnabled: boolean;
  events: ReadEvent[];
};
export const activityKey = "prism:v1:reader";
const categories: Category[] = ["politics", "economy", "society", "technology"];
export function emptyReader(): ReaderState {
  return { version: 1, displayName: "독자", trackingEnabled: true, events: [] };
}
export function restoreReader(raw: string | null): ReaderState {
  try {
    const data = JSON.parse(raw || "null");
    if (!data || data.version !== 1 || !Array.isArray(data.events))
      return emptyReader();
    const events = data.events
      .filter(
        (event: Partial<ReadEvent>) =>
          event &&
          typeof event.storyId === "string" &&
          typeof event.title === "string" &&
          categories.includes(event.category as Category) &&
          typeof event.readAt === "string" &&
          !!dateKey(event.readAt) &&
          Array.isArray(event.publisherIds) &&
          event.publisherIds.every((id) => typeof id === "string") &&
          typeof event.isDemo === "boolean",
      )
      .slice(-500);
    return {
      version: 1,
      displayName:
        typeof data.displayName === "string" && data.displayName.trim()
          ? data.displayName.trim().slice(0, 20)
          : "독자",
      trackingEnabled: data.trackingEnabled !== false,
      events,
    };
  } catch {
    return emptyReader();
  }
}
export function addRead(
  state: ReaderState,
  story: Story,
  readAt: string,
): ReaderState {
  const day = dateKey(readAt);
  if (
    !state.trackingEnabled ||
    !day ||
    state.events.some(
      (event) => event.storyId === story.id && dateKey(event.readAt) === day,
    )
  )
    return state;
  const event: ReadEvent = {
    storyId: story.id,
    title: story.title,
    category: story.category,
    publisherIds: [
      ...new Set(story.articles.map((article) => article.publisher_id)),
    ],
    readAt,
    isDemo: story.is_demo,
  };
  return { ...state, events: [...state.events, event].slice(-500) };
}
export function readingStats(events: ReadEvent[], today: string) {
  const days = Array.from({ length: 7 }, (_, index) =>
    moveDay(today, index - 6),
  );
  const week = events.filter((event) => {
    const day = dateKey(event.readAt);
    return day >= days[0] && day <= today;
  });
  const topics = categories.map((category) => ({
    category,
    count: week.filter((event) => event.category === category).length,
  }));
  return {
    total: week.length,
    topicCount: topics.filter((topic) => topic.count > 0).length,
    publisherCount: new Set(week.flatMap((event) => event.publisherIds)).size,
    demoCount: week.filter((event) => event.isDemo).length,
    topics,
    days: days.map((day) => ({
      day,
      count: week.filter((event) => dateKey(event.readAt) === day).length,
    })),
  };
}
