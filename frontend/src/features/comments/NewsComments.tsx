import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { MessageCircle, X } from "lucide-react";
import type { NewsComment } from "../../hooks/useSocialWorkspace";
import { useAccount } from '../account/AccountProvider';
export function NewsComments({
  storyId,
  title,
  comments,
  onClose,
  onAdd,
  onRemove,
}: {
  storyId: string;
  title: string;
  comments: NewsComment[];
  onClose: () => void;
  onAdd: (id: string, text: string) => void;
  onRemove: (id: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const account = useAccount();
  const rows = comments.filter((c) => c.storyId === storyId);
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="comments-dialog"
          aria-describedby="comments-description"
        >
          <header>
            <Dialog.Title>
              댓글 <small>{rows.length}</small>
            </Dialog.Title>
            <Dialog.Close className="social-icon" aria-label="댓글 닫기">
              <X />
            </Dialog.Close>
          </header>
          <Dialog.Description id="comments-description">
            {title}
          </Dialog.Description>
          <p className="local-only-note">
            {account.user ? '내 계정에 저장한 댓글입니다.' : '이 브라우저에 저장한 댓글입니다.'} 다른 사용자에게 공개되지 않습니다.
          </p>
          <div className="comment-list">
            {rows.length ? (
              rows.map((c) => (
                <article key={c.id}>
                  <span className="nav-profile">나</span>
                  <div>
                    <strong>
                      나{" "}
                      <small>
                        {new Date(c.createdAt).toLocaleDateString("ko-KR")}
                      </small>
                    </strong>
                    <p>{c.text}</p>
                    <button
                      onClick={() => onRemove(c.id)}
                      aria-label={`${c.text.slice(0, 25)} 댓글 삭제`}
                    >
                      삭제
                    </button>
                  </div>
                </article>
              ))
            ) : (
              <div className="comments-empty">
                <MessageCircle size={35} />
                <h3>첫 생각을 남겨보세요.</h3>
                <p>이 뉴스에 대해 어떤 생각이 드시나요?</p>
              </div>
            )}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (draft.trim()) {
                onAdd(storyId, draft);
                setDraft("");
              }
            }}
          >
            <input
              aria-label="댓글 입력"
              placeholder="댓글 달기…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={1000}
            />
            <button type="submit" disabled={!draft.trim()}>
              게시
            </button>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
