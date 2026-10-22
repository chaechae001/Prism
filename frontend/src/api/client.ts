import type {
  CategoriesResponse,
  FeedFilters,
  FeedResponse,
  FeedbackRequest,
  FeedbackResponse,
  StoryResponse,
} from "./types";
export const apiMode = import.meta.env.VITE_API_MODE || "mock";
export const apiVersion = "v1";
export const apiOrigin =
  apiMode === "http"
    ? import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"
    : "";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public requestId: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiOrigin}/api/${apiVersion}${path}`, options);
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError(
      "API 서버에 연결하지 못했습니다. 서버 실행·주소·CORS 설정을 확인해주세요.",
      0,
      "unavailable",
    );
  }
  const requestId = response.headers.get("X-Request-ID") || "unknown";
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(
      "API가 JSON 대신 다른 응답을 반환했습니다. 서버 주소와 오류 로그를 확인해주세요.",
      response.status,
      requestId,
    );
  }
  if (!response.ok) {
    const body = data as {
      error?: { message?: string; request_id?: string };
    } | null;
    throw new ApiError(
      body?.error?.message || "요청을 처리하지 못했습니다.",
      response.status,
      body?.error?.request_id || requestId,
    );
  }
  return data as T;
}
export const api = {
  categories: (signal?: AbortSignal) =>
    request<CategoriesResponse>("/categories", { signal }),
  feed: (filters: FeedFilters, cursor: string | null, signal?: AbortSignal) => {
    const params = new URLSearchParams({
      q: filters.q,
      mode: filters.mode,
      diversity: String(filters.diversity),
      limit: "6",
    });
    if (filters.category) params.set("category", filters.category);
    if (cursor) params.set("cursor", cursor);
    return request<FeedResponse>(`/stories?${params}`, {
      signal,
      headers: { "X-Mock-Scenario": filters.scenario },
    });
  },
  story: (id: string, signal?: AbortSignal) =>
    request<StoryResponse>(`/stories/${encodeURIComponent(id)}`, { signal }),
  feedback: (body: FeedbackRequest) =>
    request<FeedbackResponse>("/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};
