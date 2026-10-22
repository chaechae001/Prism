import { apiMode, apiOrigin } from "./client";
import type { components } from "./social-schema";
export type ChatReply = components["schemas"]["ChatReply"];
export type ChatStatus = components["schemas"]["ChatStatus"];
const origin = apiMode === "http" ? apiOrigin : "";
export async function socialRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${origin}/api/social${path}`, init);
  } catch {
    throw new Error(
      "뉴스 DM 서버에 연결하지 못했습니다. FastAPI social_api 실행 상태를 확인해주세요.",
    );
  }
  let value;
  try {
    value = await response.json();
  } catch {
    throw new Error("뉴스 DM 서버를 실행한 뒤 다시 시도해주세요.");
  }
  if (!response.ok)
    throw new Error(
      value.error?.message || value.detail || "답변을 받아오지 못했습니다.",
    );
  return value as T;
}
