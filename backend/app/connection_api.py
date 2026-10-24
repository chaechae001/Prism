"""News API with swappable data sources.

python -m uvicorn app.connection_api:app --app-dir backend --host 127.0.0.1 --port 8000
"""
import logging
import os
import time
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .connection_repository import SOURCES, Snapshot, load_snapshot, resolve_story
from .cluster_preview import ClusterPreviewError
from .cluster_feed import ClusterFeedError
from .db import DatabaseConfigurationError
from .models import (CategoriesResponse, Category, CategoryInfo, ErrorResponse, FeedMeta,
                     FeedResponse, FeedbackRequest, FeedbackResponse, Mode, StoryResponse)
from .recommendation import cursor_key, decode_cursor, encode_cursor, rank

logger = logging.getLogger("prism.connection")
source = os.getenv("PRISM_DATA_SOURCE", "fixture")
if source not in SOURCES:
    raise RuntimeError("PRISM_DATA_SOURCE must be one of: " + ", ".join(sorted(SOURCES)))
app = FastAPI(title="Prism connection API (development)", version="1.0.0",
              responses={code: {"model": ErrorResponse} for code in (404, 422, 500, 503)})
origins = [value.strip() for value in os.getenv("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if value.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "X-Mock-Scenario"],
                   expose_headers=["X-Request-ID", "X-Prism-Data-Source"])


def failure(request, status, code, message, details=None):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message,
                        "details": details or [], "request_id": request.state.request_id}})


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    try:
        response = await call_next(request)
    except Exception as exc:
        # Neither DB exception text nor URLs/credentials are logged or returned.
        logger.error("request_failed request_id=%s exception_type=%s", request.state.request_id, type(exc).__name__)
        response = failure(request, 500, "INTERNAL_ERROR", "데이터를 읽지 못했습니다. 서버의 데이터 소스 설정과 연결 상태를 확인해주세요.")
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Prism-Data-Source"] = source
    # Add CORS also when an unexpected error occurred outside CORSMiddleware's response.
    if request.headers.get("origin") in origins:
        response.headers["Access-Control-Allow-Origin"] = request.headers["origin"]
        response.headers["Access-Control-Expose-Headers"] = "X-Request-ID, X-Prism-Data-Source"
        response.headers.add_vary_header("Origin")
    return response


@app.exception_handler(DatabaseConfigurationError)
def database_configuration_error(request, exc):
    return failure(request, 503, "DATABASE_NOT_CONFIGURED", "DB 연결 설정을 확인해주세요.")


@app.exception_handler(ClusterPreviewError)
def cluster_results_error(request, exc):
    return failure(request, 503, "CLUSTER_RESULTS_UNAVAILABLE", "로컬 군집 결과 파일이 없거나 서로 일치하지 않습니다. 결과 폴더를 확인해주세요.")


@app.exception_handler(ClusterFeedError)
def cluster_db_error(request,exc):
    return failure(request,503,"CLUSTER_DB_UNAVAILABLE","DB 군집 결과를 읽지 못했습니다. 연결과 전용 테이블 설정을 확인해주세요.")


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return failure(request, exc.status_code, {404: "NOT_FOUND", 422: "VALIDATION_ERROR", 503: "MOCK_ERROR"}.get(exc.status_code, "HTTP_ERROR"), str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    details = [{"loc": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]
    return failure(request, 422, "VALIDATION_ERROR", "요청 값을 확인해주세요.", details)


def get_snapshot() -> Snapshot:
    return load_snapshot(source)


Data = Annotated[Snapshot, Depends(get_snapshot)]


@app.get("/health")
def health():
    # Liveness only. Does not contact the DB and makes no readiness claim.
    return {"status": "ok", "dataset_version": f"connection-{source}"}


@app.get("/api/v1/categories", response_model=CategoriesResponse)
def categories(data: Data):
    names = {"politics": "정치", "economy": "경제", "society": "사회", "technology": "기술"}
    return CategoriesResponse(items=[CategoryInfo(id=k, label=v, count=sum(s.category == k for s in data.stories)) for k, v in names.items()])


@app.get("/api/v1/stories", response_model=FeedResponse)
def stories(request: Request, data: Data, q: str = Query(default="", max_length=100),
            category: Category | None = None, mode: Mode = "balanced",
            diversity: int = Query(default=70, ge=0, le=100), limit: int = Query(default=6, ge=1, le=20),
            cursor: str | None = Query(default=None, max_length=1000),
            scenario: str | None = Header(default=None, alias="X-Mock-Scenario")):
    if data.is_mock and scenario == "error":
        raise HTTPException(503, "테스트용 API 오류입니다.")
    if data.is_mock and scenario == "slow":
        time.sleep(2)
    q = q.strip()
    pool = [s for s in data.stories if (category is None or s.category == category) and q.casefold() in " ".join([s.title, s.dek, *s.keywords]).casefold()]
    if data.is_mock and scenario == "empty":
        pool = []
    ranked, relaxed = rank(pool, mode, diversity)
    if data.source in {"cluster-local","cluster-db"}:
        for item in ranked:
            item.reason.label = "군집분석 결과 · 동일 사건 검토 전"
    elif data.preview:
        for item in ranked:
            item.reason.label = "RSS 원문 미리보기 · 군집/AI 요약 전"
    key = cursor_key(data.version, q, category, mode, diversity)
    try:
        offset = decode_cursor(cursor, key, len(ranked)) if cursor else 0
    except ValueError:
        raise HTTPException(422, "현재 검색 조건이나 데이터와 일치하지 않는 커서입니다.") from None
    page = ranked[offset:offset + limit]
    return FeedResponse(items=page, total=len(ranked),
        next_cursor=encode_cursor(key, offset + limit) if offset + limit < len(ranked) else None,
        meta=FeedMeta(request_id=request.state.request_id, generated_at=datetime.now(timezone.utc),
            dataset_version=data.version, is_mock=data.is_mock, mode=mode, diversity=diversity,
            policy_version=data.source+"-v1" if data.source in {"cluster-local","cluster-db"} else "rss-preview-v1" if data.preview else "connection-v1", policy_notes=data.notes + ["주제·출처 정렬은 개발용입니다. 정치적 편향 평가나 AI 중립성 검증 결과가 아닙니다."],
            returned_categories=list(dict.fromkeys(i.story.category for i in page)), source_cap_relaxed=relaxed))


@app.get("/api/v1/stories/{story_id}", response_model=StoryResponse)
def story(story_id: str, request: Request, data: Data):
    value = resolve_story(data, story_id)
    if value is None:
        raise HTTPException(404, "해당 사건을 찾을 수 없습니다.")
    return StoryResponse(story=value, request_id=request.state.request_id, is_mock=data.is_mock)


@app.post("/api/v1/feedback", response_model=FeedbackResponse, status_code=201)
def feedback(body: FeedbackRequest, request: Request, data: Data):
    if resolve_story(data, body.story_id) is None:
        raise HTTPException(404, "해당 사건을 찾을 수 없습니다.")
    # Explicitly ephemeral: no fake claim of persistence.
    return FeedbackResponse(id=str(uuid4()), request_id=request.state.request_id, persisted=False)
