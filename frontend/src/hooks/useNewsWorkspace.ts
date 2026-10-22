import { useEffect, useMemo, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Category, FeedFilters, Mode, Scenario } from "../api/types";
import {
  visibleItems,
  type View,
  type DetailTab,
} from "../presentation/timeline";

const categories = ["politics", "economy", "society", "technology"];
function readSaved(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem("prism:v1:saved") || "[]");
    return Array.isArray(value)
      ? [...new Set(value.filter((id): id is string => typeof id === "string"))]
      : [];
  } catch {
    return [];
  }
}
export function useNewsWorkspace() {
  const [url, setUrl] = useState(() => new URL(location.href));
  useEffect(() => {
    const onBack = () => setUrl(new URL(location.href));
    addEventListener("popstate", onBack);
    return () => removeEventListener("popstate", onBack);
  }, []);
  const update = (values: Record<string, string | null>) => {
    const next = new URL(location.href);
    Object.entries(values).forEach(([key, value]) => {
      if (value === null || value === "") next.searchParams.delete(key);
      else next.searchParams.set(key, value);
    });
    if (next.href !== location.href) history.pushState({}, "", next);
    setUrl(next);
  };
  const params = url.searchParams;
  const q = (params.get("q") || "").slice(0, 100);
  const rawCategory = params.get("category") || "";
  const category = (categories.includes(rawCategory) ? rawCategory : "") as
    Category | "";
  const rawView =
    params.get("view") === "saved"
      ? "mypage"
      : params.get("view") || "timeline";
  const view = (
    ["timeline", "briefing", "categories", "mypage", "chat"].includes(rawView)
      ? rawView
      : "timeline"
  ) as View;
  const rawMode = params.get("mode") || "balanced";
  const mode = (
    ["balanced", "latest", "explore"].includes(rawMode) ? rawMode : "balanced"
  ) as Mode;
  const rawDiversity = Number(params.get("diversity") ?? 70);
  const diversity =
    Number.isInteger(rawDiversity) && rawDiversity >= 0 && rawDiversity <= 100
      ? rawDiversity
      : 70;
  // Dates are browsed in edition stories; legacy calendar query parameters no longer filter the feed.
  const day = "";
  const from = "";
  const to = "";
  const dm = params.get("dm");
  const selected = params.get("story");
  const rawTab = params.get("panel") || "summary";
  const detailTab = (
    [
      "summary",
      "perspectives",
      "sources",
      "five_w",
      "easy",
      "sentiment",
    ].includes(rawTab)
      ? rawTab
      : "summary"
  ) as DetailTab;
  const [scenario, setScenario] = useState<Scenario>("normal");
  const [saved, setSaved] = useState(readSaved);
  const [storageError, setStorageError] = useState(false);
  useEffect(() => {
    try {
      localStorage.setItem("prism:v1:saved", JSON.stringify(saved));
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
  }, [saved]);
  const toggleSave = (id: string) =>
    setSaved((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [...current, id],
    );
  const filters: FeedFilters = {
    q,
    category,
    mode,
    diversity,
    scenario,
  };
  const feed = useInfiniteQuery({
    queryKey: ["feed", filters],
    queryFn: ({ pageParam, signal }) => api.feed(filters, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: view !== "mypage",
    retry: false,
  });
  const categoryQuery = useQuery({
    queryKey: ["categories"],
    queryFn: ({ signal }) => api.categories(signal),
  });
  const savedQuery = useQuery({
    queryKey: ["saved", saved],
    enabled: view === "mypage",
    queryFn: async ({ signal }) => {
      const rows = await Promise.allSettled(
        saved.map((id) => api.story(id, signal)),
      );
      const items = rows.flatMap((row) =>
        row.status === "fulfilled"
          ? [
              {
                story: row.value.story,
                reason: {
                  code: "public_interest" as const,
                  label: "내가 저장한 사건",
                },
              },
            ]
          : [],
      );
      return {
        items,
        unavailable: rows.filter((row) => row.status === "rejected").length,
      };
    },
  });
  const items = useMemo(
    () =>
      view === "mypage"
        ? savedQuery.data?.items || []
        : feed.data?.pages.flatMap((page) => page.items) || [],
    [view, savedQuery.data, feed.data],
  );
  const displayed = useMemo(
    () => visibleItems(items, day, from, to),
    [items, day, from, to],
  );
  const loading = view === "mypage" ? savedQuery.isPending : feed.isPending;
  const eventDates = useMemo(
    () =>
      Object.assign(
        {},
        ...(feed.data?.pages || []).map((page) =>
          "event_dates" in page.meta ? page.meta.event_dates : {},
        ),
      ) as Record<string, string>,
    [feed.data],
  );
  const error = view === "mypage" ? savedQuery.error : feed.error;
  const total =
    view === "mypage" ? saved.length : feed.data?.pages[0].total || 0;
  const clearDates = () => update({ date: "all", from: null, to: null });
  const reset = () => {
    setScenario("normal");
    update({
      q: null,
      category: null,
      view: null,
      mode: null,
      diversity: null,
      date: null,
      from: null,
      to: null,
      story: null,
      panel: null,
    });
  };
  const explore = () => {
    setScenario("normal");
    update({
      view: "briefing",
      mode: "explore",
      diversity: "90",
      category: null,
      q: null,
      date: null,
      from: null,
      to: null,
    });
  };
  return {
    q,
    category,
    view,
    mode,
    diversity,
    day,
    from,
    to,
    selected,
    detailTab,
    dm,
    scenario,
    setScenario,
    saved,
    toggleSave,
    storageError,
    feed,
    categoryQuery,
    savedQuery,
    items,
    displayed,
    eventDates,
    loading,
    error,
    total,
    update,
    clearDates,
    reset,
    explore,
  };
}
