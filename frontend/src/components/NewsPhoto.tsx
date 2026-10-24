import { useState } from "react";
import { Newspaper } from "lucide-react";
import type { Story } from "../api/types";

// Illustrative stock photography is limited to fictional demo stories.
// The API supplies original article media; cluster-local is a local preview only.
const demos: Record<Story["visual"], string> = {
  city: "photo-1519608487953-e999c86e7455",
  chip: "photo-1518770660439-4636190af475",
  energy: "photo-1508514177221-188b1cf16e9d",
  school: "photo-1509062522246-3755977927d7",
  market: "photo-1486406146926-c627a92ad1ab",
  assembly: "photo-1529107386315-e1a2ed48a620",
  work: "photo-1497366811353-6870744d04b2",
  research: "photo-1532094349884-543bc11b234d",
};
export function NewsPhoto({
  story,
  compact = false,
}: {
  story: Story;
  compact?: boolean;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const representative = story.articles[0];
  const imageUrl = story.is_demo
    ? `https://images.unsplash.com/${demos[story.visual]}?auto=format&fit=crop&w=${compact ? 360 : 1000}&q=80`
    : representative?.image_url || null;
  const available = !!imageUrl && failedUrl !== imageUrl;
  return (
    <span className={`social-photo ${compact ? "compact" : ""}`}>
      {available ? (
        <img
          src={imageUrl}
          alt={story.is_demo ? `${story.title} · 사건과 무관한 예시 사진` : `${representative.title} · 기사 이미지`}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailedUrl(imageUrl)}
        />
      ) : (
        <span className={`photo-placeholder photo-${story.visual}`}>
          <Newspaper size={compact ? 26 : 54} />
          <span>PRISM NEWS</span>
          {!compact && <small>{imageUrl ? "기사 사진을 불러오지 못했습니다" : "기사 사진이 제공되지 않았습니다"}</small>}
        </span>
      )}
      {!compact && available && (
        <small className="photo-disclaimer">
          {story.is_demo ? "예시 사진 · 실제 사건 사진 아님" : `기사 이미지 · ${representative.publisher_name}`}
        </small>
      )}
    </span>
  );
}
