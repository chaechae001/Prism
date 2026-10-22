import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowUpRight,
  Bookmark,
  ChevronLeft,
  ChevronRight,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Story } from "../api/types";
import { categoryNames } from "../presentation/timeline";
import { NewsPhoto } from "./NewsPhoto";

export function NewsReel({
  stories,
  initial,
  onClose,
  onOpen,
  saved,
  onSave,
}: {
  stories: Story[];
  initial: number;
  onClose: () => void;
  onOpen: (id: string) => void;
  saved: string[];
  onSave: (id: string) => void;
}) {
  const [index, setIndex] = useState(initial);
  const touchStart = useRef<number | null>(null);
  const story = stories[index];
  useEffect(() => {
    const keys = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") setIndex((v) => Math.max(0, v - 1));
      if (event.key === "ArrowRight")
        setIndex((v) => Math.min(stories.length - 1, v + 1));
    };
    addEventListener("keydown", keys);
    return () => removeEventListener("keydown", keys);
  }, [stories.length]);
  if (!story) return null;
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="reel-overlay" />
        <Dialog.Content
          className="news-reel"
          aria-describedby="reel-description"
          onTouchStart={(event) => {
            touchStart.current = event.touches[0]?.clientX ?? null;
          }}
          onTouchEnd={(event) => {
            if (touchStart.current === null) return;
            const distance =
              (event.changedTouches[0]?.clientX ?? touchStart.current) -
              touchStart.current;
            if (Math.abs(distance) > 60)
              setIndex((v) =>
                Math.max(
                  0,
                  Math.min(stories.length - 1, v + (distance < 0 ? 1 : -1)),
                ),
              );
            touchStart.current = null;
          }}
        >
          <div
            className="reel-progress"
            aria-label={`${stories.length}개 중 ${index + 1}번째 뉴스`}
          >
            {stories.map((s, i) => (
              <span key={s.id} className={i <= index ? "seen" : ""} />
            ))}
          </div>
          <header>
            <span className="post-avatar">p·</span>
            <Dialog.Title>
              최근 뉴스 <small>{categoryNames[story.category]}</small>
            </Dialog.Title>
            <Dialog.Close className="social-icon" aria-label="최근 뉴스 닫기">
              <X />
            </Dialog.Close>
          </header>
          <NewsPhoto key={story.id} story={story} />
          <div className="reel-shade" />
          <div className="reel-story-copy">
            <span>{story.is_demo ? "DEMO · 가상 뉴스" : "PRISM NEWS"}</span>
            <h2>{story.title}</h2>
            <p id="reel-description">
              {story.summary.status === "ready"
                ? story.summary.bullets[0]?.text || story.dek
                : story.dek}
            </p>
            <div>
              <button
                onClick={() => {
                  onClose();
                  onOpen(story.id);
                }}
              >
                기사 자세히 보기 <ArrowUpRight size={16} />
              </button>
              <button
                className="social-icon"
                onClick={() => onSave(story.id)}
                aria-label={
                  saved.includes(story.id)
                    ? "최근 뉴스 저장 취소"
                    : "최근 뉴스 저장"
                }
                aria-pressed={saved.includes(story.id)}
              >
                <Bookmark
                  fill={saved.includes(story.id) ? "currentColor" : "none"}
                />
              </button>
            </div>
          </div>
          <button
            className="reel-previous"
            aria-label="이전 뉴스"
            disabled={index === 0}
            onClick={() => setIndex((v) => v - 1)}
          >
            <ChevronLeft />
          </button>
          <button
            className="reel-next"
            aria-label="다음 뉴스"
            disabled={index === stories.length - 1}
            onClick={() => setIndex((v) => v + 1)}
          >
            <ChevronRight />
          </button>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
