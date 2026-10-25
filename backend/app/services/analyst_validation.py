"""Offline batch checks and a read-only plan for importing existing article bodies."""

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import bindparam, text

from ..db import get_engine
from ..models import AnalystBatch, ArticleInput

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ARTICLES = 1000
MAX_BODY_CHARS = 200_000


@dataclass
class CheckedBatch:
    batch: AnalystBatch | None
    report: dict


class InvalidAnalystBatch(ValueError):
    code = "INVALID_ANALYST_BATCH"

    def __init__(self, report):
        super().__init__(self.code)
        self.report = report


def issue(code, message, index=None, field=None):
    return {"code": code, "message": message, "article_index": index, "field": field}


def check_batch(payload) -> CheckedBatch:
    errors, warnings = [], []
    articles = payload.articles if isinstance(payload, AnalystBatch) else payload.get("articles") if isinstance(payload, dict) else None
    if isinstance(articles, list) and len(articles) > MAX_ARTICLES:
        return CheckedBatch(None, _report(0, [issue("BATCH_TOO_LARGE", "배치는 최대 1,000건까지 나누어 주세요.")], []))
    try:
        batch = AnalystBatch.model_validate(payload)
    except ValidationError as exc:
        for error in exc.errors(include_url=False, include_input=False):
            loc = error["loc"]
            index = loc[1] if len(loc) > 1 and loc[0] == "articles" and isinstance(loc[1], int) else None
            # Do not echo unknown field names or any untrusted input values.
            field = loc[-1] if loc and loc[-1] in {
                "schema_version", "batch_id", "articles", *ArticleInput.model_fields
            } else None
            errors.append(issue("INVALID_STRUCTURE", "필수 필드·자료형·시간대·카테고리를 확인해주세요.", index, field))
        return CheckedBatch(None, _report(0, errors, []))
    if not batch.batch_id.strip():
        errors.append(issue("EMPTY_BATCH_ID", "batch_id가 비어 있습니다.", field="batch_id"))
    ids, urls, hashes = set(), set(), set()
    eligible = 0
    for index, article in enumerate(batch.articles):
        for field in ("id", "publisher_id", "publisher_group_id", "title", "text"):
            if not getattr(article, field).strip():
                errors.append(issue("BLANK_FIELD", "공백만 있는 필드는 사용할 수 없습니다.", index, field))
        url = str(article.canonical_url)
        if article.canonical_url.username or article.canonical_url.password:
            errors.append(issue("URL_CREDENTIALS", "기사 URL에 접속 정보를 넣지 마세요.", index, "canonical_url"))
        if article.id in ids:
            errors.append(issue("DUPLICATE_ID", "같은 배치에 기사 ID가 중복됩니다.", index, "id"))
        if url in urls:
            errors.append(issue("DUPLICATE_URL", "같은 배치에 원문 URL이 중복됩니다.", index, "canonical_url"))
        ids.add(article.id)
        urls.add(url)
        digest = sha256(article.text.encode("utf-8")).hexdigest()
        if article.content_hash != digest:
            errors.append(issue("HASH_MISMATCH", "전달한 본문 UTF-8 바이트의 SHA-256과 일치하지 않습니다.", index, "content_hash"))
        if digest in hashes:
            warnings.append(issue("DUPLICATE_BODY", "다른 기사와 본문이 같습니다. 출처를 확인해주세요. 자동 제거하지 않습니다.", index, "text"))
        hashes.add(digest)
        if len(article.text) > MAX_BODY_CHARS:
            errors.append(issue("BODY_TOO_LARGE", "기사 본문은 최대 200,000자까지 입력합니다.", index, "text"))
        elif len(article.text) > 30_000:
            warnings.append(issue("SUMMARY_EXCERPT", "현재 요약기는 본문 앞 30,000자까지만 사용합니다.", index, "text"))
        if article.collected_at < article.published_at:
            errors.append(issue("INVALID_TIME_ORDER", "수집 시각이 발행 시각보다 앞섭니다.", index, "collected_at"))
        if article.license_status == "allowed" and {"collect", "store"} <= set(article.allowed_uses):
            eligible += 1
            if not {"summarize", "publish_summary"} <= set(article.allowed_uses):
                warnings.append(issue("SUMMARY_NOT_ALLOWED", "수집·저장은 가능하지만 요약·요약 게시 조건이 충족되지 않았습니다.", index, "allowed_uses"))
        else:
            errors.append(issue("STORAGE_NOT_ALLOWED", "수집·저장이 허용된 기사만 본문을 입력할 수 있습니다.", index, "allowed_uses"))
    return CheckedBatch(batch, _report(len(batch.articles), errors, warnings, eligible))


def _report(count, errors, warnings, eligible=0):
    return {"valid": not errors, "article_count": count, "storage_eligible_count": eligible,
            "errors": errors, "warnings": warnings, "database_checked": False, "written": False}


def read_checked_batch(path: Path) -> CheckedBatch:
    try:
        with path.open("rb") as file:
            raw = file.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            return CheckedBatch(None, _report(0, [issue("FILE_TOO_LARGE", "JSON 파일은 최대 25MiB까지 입력합니다.")], []))
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, ValueError, RecursionError):
        return CheckedBatch(None, _report(0, [issue("INVALID_FILE", "UTF-8 JSON 파일의 경로·인코딩·내용을 확인해주세요.")], []))
    return check_batch(payload)


def plan_import(checked: CheckedBatch, *, engine=None):
    report = {**checked.report}
    if not report["valid"] or checked.batch is None:
        return report
    batch = checked.batch
    with (engine or get_engine()).connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        rows = connection.execute(text("""
            SELECT id,publisher_id,canonical_url FROM public.articles
            WHERE canonical_url IN :urls
        """).bindparams(bindparam("urls", expanding=True)),
            {"urls": [str(a.canonical_url) for a in batch.articles]}).mappings().all()
    by_url = {r["canonical_url"]: r for r in rows}
    mapped, missing, mismatch = [], [], []
    for index, article in enumerate(batch.articles):
        row = by_url.get(str(article.canonical_url))
        if row is None:
            missing.append(index)
        elif row["publisher_id"] != article.publisher_id:
            mismatch.append(index)
        else:
            mapped.append(index)
    report.update(database_checked=True, ready_for_import=not missing and not mismatch,
                  mapping={"matched_count": len(mapped), "missing_article_indices": missing,
                           "publisher_mismatch_indices": mismatch},
                  notice="읽기 전용 검사입니다. 기사 미등록이면 메타데이터를 먼저 등록한 뒤 다시 확인해주세요.")
    return report
