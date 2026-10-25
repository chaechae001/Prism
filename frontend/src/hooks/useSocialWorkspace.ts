import { useEffect, useState } from "react";
import type { Story } from "../api/types";
import { useAccount } from '../features/account/AccountProvider';

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  createdAt: string;
  articleIds?: string[];
  model?: string;
};
export type NewsThread = {
  id: string;
  title: string;
  category: Story["category"];
  messages: ChatMessage[];
};
export type NewsComment = {
  id: string;
  storyId: string;
  text: string;
  createdAt: string;
};
type SocialData = { threads: NewsThread[]; comments: NewsComment[] };
const storageKey = "prism:social:v1";
const categories = ["politics", "economy", "society", "technology"];
function read(): SocialData {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (
      !value ||
      !Array.isArray(value.threads) ||
      !Array.isArray(value.comments)
    )
      return { threads: [], comments: [] };
    const threads = value.threads
      .slice(0, 50)
      .filter(
        (t: NewsThread) =>
          typeof t?.id === "string" &&
          t.id.length <= 100 &&
          typeof t.title === "string" &&
          categories.includes(t.category) &&
          Array.isArray(t.messages),
      )
      .map((t: NewsThread) => ({
        ...t,
        messages: t.messages
          .filter(
            (m) =>
              m &&
              ["user", "assistant"].includes(m.role) &&
              typeof m.text === "string" &&
              typeof m.id === "string" &&
              typeof m.createdAt === "string",
          )
          .slice(-100),
      }));
    const comments = value.comments
      .filter(
        (c: NewsComment) =>
          c &&
          typeof c.id === "string" &&
          typeof c.storyId === "string" &&
          typeof c.text === "string" &&
          typeof c.createdAt === "string",
      )
      .slice(-500);
    return { threads, comments };
  } catch {
    return { threads: [], comments: [] };
  }
}
export function useSocialWorkspace() {
  const account = useAccount();
  const [data, setData] = useState<SocialData>(read);
  const [storageError, setStorageError] = useState(false);
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(data));
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
  }, [data]);
  const openThread = (story: Story) => {
    if (account.loading) return;
    if (account.user) { account.mutate(`/threads/${encodeURIComponent(story.id)}`, 'POST'); return; }
    setData((current) => ({
      ...current,
      threads: [
        {
          id: story.id,
          title: story.title,
          category: story.category,
          messages:
            current.threads.find((t) => t.id === story.id)?.messages || [],
        },
        ...current.threads.filter((t) => t.id !== story.id),
      ].slice(0, 50),
    }));
  };
  const append = (id: string, message: Omit<ChatMessage, "id" | "createdAt">) => {
    if (account.user) {
      if (message.role === 'assistant') void account.reload().catch(() => {});
      return; // Authenticated exchanges are validated and saved by the server.
    }
    setData((current) => ({
      ...current,
      threads: current.threads.map((t) =>
        t.id === id
          ? {
              ...t,
              messages: [
                ...t.messages,
                {
                  ...message,
                  id: crypto.randomUUID(),
                  createdAt: new Date().toISOString(),
                },
              ].slice(-100),
            }
          : t,
      ),
    }));
  };
  const addComment = (storyId: string, text: string) => {
    const trimmed = text.trim().slice(0, 1000);
    if (account.loading) return;
    if (account.user) { if (trimmed) account.mutate('/comments', 'POST', { story_id: storyId, text: trimmed }); return; }
    if (trimmed)
      setData((current) => ({
        ...current,
        comments: [
          ...current.comments,
          {
            id: crypto.randomUUID(),
            storyId,
            text: trimmed,
            createdAt: new Date().toISOString(),
          },
        ].slice(-500),
      }));
  };
  const removeComment = (id: string) => {
    if (account.user) { account.mutate(`/comments/${encodeURIComponent(id)}`, 'DELETE'); return; }
    setData((current) => ({
      ...current,
      comments: current.comments.filter((c) => c.id !== id),
    }));
  };
  return {
    ...(account.user ? account.workspace : account.loading ? { threads: [], comments: [] } : data),
    storageError,
    openThread,
    append,
    addComment,
    removeComment,
  };
}
