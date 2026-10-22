import { useState } from "react";
import { Newspaper } from "lucide-react";
import type { Story } from "../api/types";

// Illustrative stock photography is limited to fictional demo stories.
// Real article media needs an agreed API field and display permission first.
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
  const [failed, setFailed] = useState(false);
  return (
    <span className={`social-photo ${compact ? "compact" : ""}`}>
      {story.is_demo && !failed ? (
        <img
          src={`https://images.unsplash.com/${demos[story.visual]}?auto=format&fit=crop&w=${compact ? 360 : 1000}&q=80`}
          alt={`${story.title} · 사건과 무관한 예시 사진`}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className={`photo-placeholder photo-${story.visual}`}>
          <Newspaper size={compact ? 26 : 54} />
          <span>PRISM NEWS</span>
          {!compact && <small>기사 사진이 제공되지 않았습니다</small>}
        </span>
      )}
      {!compact && story.is_demo && !failed && (
        <small className="photo-disclaimer">
          예시 사진 · 실제 사건 사진 아님
        </small>
      )}
    </span>
  );
}
