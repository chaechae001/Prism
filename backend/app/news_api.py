"""Read-only v2 server. All ingestion/review writes are offline CLI jobs."""

import logging
import os
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .news.router import router
from .news.config import load_env_file

if os.getenv("NEWS_ENV_FILE"):
    load_env_file(os.environ["NEWS_ENV_FILE"])

app = FastAPI(title="Prism News API v2", version="2.0.0")
origins = [
    s.strip()
    for s in os.getenv(
        "CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
    ).split(",")
    if s.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Request-ID"],
)


def error(request, status, code, message):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": [],
                "request_id": request.state.request_id,
            }
        },
    )


@app.middleware("http")
async def handle(request: Request, call_next):
    request.state.request_id = str(uuid4())
    try:
        response = await call_next(request)
    except Exception as exc:
        logging.getLogger("prism.news").error(
            "request_failed id=%s type=%s", request.state.request_id, type(exc).__name__
        )
        response = error(
            request,
            503,
            "NEWS_DATABASE_UNAVAILABLE",
            "뉴스 데이터 연결을 확인해주세요.",
        )
    response.headers["X-Request-ID"] = request.state.request_id
    if request.headers.get("origin") in origins:
        response.headers["Access-Control-Allow-Origin"] = request.headers["origin"]
        response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
        response.headers.add_vary_header("Origin")
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return error(
        request,
        exc.status_code,
        "NOT_FOUND" if exc.status_code == 404 else "VALIDATION_ERROR",
        str(exc.detail),
    )


@app.exception_handler(RequestValidationError)
async def invalid(request, exc):
    return error(request, 422, "VALIDATION_ERROR", "요청 형식을 확인해주세요.")


@app.get("/health")
def health():
    return {"status": "ok", "mode": "news-v2", "database_checked": False}


app.include_router(router)
