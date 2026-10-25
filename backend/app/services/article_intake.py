"""Plan or atomically register article metadata and bodies without publishing."""
from hashlib import sha256

from sqlalchemy import bindparam, text

from ..db import get_engine
from ..models import AnalystBatch
from .analyst_validation import InvalidAnalystBatch, check_batch, issue
from .body_import import _store_bodies


class IntakeConflict(ValueError):
    code = "ARTICLE_INTAKE_CONFLICT"

    def __init__(self, report):
        super().__init__(self.code)
        self.report = report


def _article_id(url):
    return "article-" + sha256(str(url).encode("utf-8")).hexdigest()


def intake_articles(batch: AnalystBatch, *, apply=False, is_demo=False, engine=None):
    checked = check_batch(batch)
    if not checked.report["valid"]:
        raise InvalidAnalystBatch(checked.report)
    selected_engine = engine or get_engine()
    context = selected_engine.begin() if apply else selected_engine.connect()
    with context as connection:
        if not apply:
            connection.execute(text("SET TRANSACTION READ ONLY"))
        publishers = connection.execute(text("""
            SELECT id,group_id FROM public.publishers WHERE id IN :ids
        """).bindparams(bindparam("ids", expanding=True)),
            {"ids": sorted({a.publisher_id for a in batch.articles})}).mappings().all()
        groups = {p["id"]: p["group_id"] for p in publishers}
        rows = connection.execute(text("""
            SELECT id,publisher_id,canonical_url,is_demo FROM public.articles
            WHERE canonical_url IN :urls OR id IN :ids
        """).bindparams(bindparam("urls", expanding=True), bindparam("ids", expanding=True)),
            {"urls": [str(a.canonical_url) for a in batch.articles],
             "ids": [_article_id(a.canonical_url) for a in batch.articles]}).mappings().all()
        by_url = {r["canonical_url"]: r for r in rows}
        by_id = {r["id"]: r for r in rows}
        errors, new, existing = [], [], 0
        for index, article in enumerate(batch.articles):
            if article.publisher_id not in groups:
                errors.append(issue("UNKNOWN_PUBLISHER", "매체 정보를 먼저 등록해주세요.", index, "publisher_id"))
            elif groups[article.publisher_id] != article.publisher_group_id:
                errors.append(issue("PUBLISHER_GROUP_MISMATCH", "DB와 입력의 출처 그룹이 다릅니다.", index, "publisher_group_id"))
            row = by_url.get(str(article.canonical_url))
            if row is not None:
                existing += 1
                if row["publisher_id"] != article.publisher_id:
                    errors.append(issue("PUBLISHER_MISMATCH", "기존 기사와 입력의 매체가 다릅니다.", index, "publisher_id"))
                if is_demo and not row["is_demo"]:
                    errors.append(issue("DEMO_EXISTING_ARTICLE", "가상 입력 모드로 실제 기사를 수정할 수 없습니다.", index))
            else:
                if _article_id(article.canonical_url) in by_id:
                    errors.append(issue("ARTICLE_ID_CONFLICT", "생성할 기사 ID가 기존 데이터와 충돌합니다.", index))
                new.append(article)
        report = {**checked.report, "database_checked": True, "ready_for_intake": not errors,
                  "applied": False, "intake_errors": errors,
                  "plan": {"new_article_count": len(new), "existing_article_count": existing},
                  "notice": "신규 기사는 비공개로 등록합니다. 군집·요약·게시를 실행하지 않습니다."}
        if not apply:
            return report
        if errors:
            raise IntakeConflict(report)
        for article in new:
            connection.execute(text("""
                INSERT INTO public.articles
                    (id,publisher_id,canonical_url,title,published_at,is_demo,publish_allowed)
                VALUES (:id,:publisher,:url,:title,:at,:demo,false)
            """), {"id": _article_id(article.canonical_url), "publisher": article.publisher_id,
                    "url": str(article.canonical_url), "title": article.title,
                    "at": article.published_at, "demo": is_demo})
        result = _store_bodies(connection, batch)
        report.update(applied=True, written=True, body_changed_count=sum(r["changed"] for r in result))
        return report
