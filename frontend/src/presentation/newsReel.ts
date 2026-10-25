/** Short excerpts for the story overlay; full text remains in the detail view. */
export function reelExcerpt(text: string): string {
  const plain = text.replace(/^대표기사 본문 발췌\s*·\s*/, "").trim();
  const characters = Array.from(plain);
  if (characters.length <= 40) return plain;
  const limit = Math.min(84, Math.ceil(characters.length / 3));
  return characters.slice(0, limit).join("").trimEnd() + "…";
}
