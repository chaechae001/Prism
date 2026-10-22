import { apiMode, apiOrigin, apiVersion } from "../api/client";
import type { FeedResponse } from "../api/types";

export function ConnectionStatus({ meta }: { meta?: FeedResponse["meta"] }) {
  return (
    <details className="connection-status">
      <summary>
        개발 연결 상태 · {apiMode === "http" ? "FastAPI HTTP" : "브라우저 Mock"}
      </summary>
      <dl>
        <div>
          <dt>API 버전</dt>
          <dd>{apiVersion}</dd>
        </div>
        <div>
          <dt>요청 경로</dt>
          <dd>{apiMode === "http" ? apiOrigin : "MSW 가상 응답"}</dd>
        </div>
        <div>
          <dt>데이터</dt>
          <dd>
            {meta ? (meta.is_mock ? "가상 자료" : "서버 데이터") : "응답 대기"}
          </dd>
        </div>
        <div>
          <dt>정책</dt>
          <dd>{meta?.policy_version || "확인 전"}</dd>
        </div>
        <div>
          <dt>데이터 버전</dt>
          <dd>{meta?.dataset_version || "확인 전"}</dd>
        </div>
      </dl>
      {meta?.policy_notes.map((note) => (
        <p key={note}>{note}</p>
      ))}
      <p>HTTP 연결 성공과 실제 기사 수집·DB·AI 처리 성공은 별도 단계입니다.</p>
    </details>
  );
}
