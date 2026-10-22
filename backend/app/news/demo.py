"""Own fictional text/results, solely to exercise the real DB flow without external keys."""

from datetime import datetime, timezone
from .analysis import import_results, publish
from .models import BodyImport, Publisher, ResultBatch
from .naver import NaverItem, normalize
from .storage import save_article, save_body, export_batch, atomic


@atomic
def seed_demo(conn):
    if conn.info.host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("DEMO_ONLY_ON_LOCAL_DATABASE")
    ids, body_items = [], []
    for index in range(1, 4):
        publisher = Publisher(
            id=f"demo-v2-{index}",
            name=f"가상 뉴스 {index}",
            group_id=f"demo-group-{index}",
            domains=[f"paper{index}.example.com"],
        )
        raw = {
            "title": f"[가상] 야간 <b>버스</b> 시범 운행 소식 {index}",
            "originallink": f"https://paper{index}.example.com/bus-night",
            "link": f"https://example.com/naver-demo-{index}",
            "description": "검색용 짧은 설명입니다. 이 필드는 기사 전문이 아닙니다.",
            "pubDate": f"Thu, 22 Oct 2026 0{index}:00:00 +0900",
        }
        article = normalize(
            NaverItem.model_validate(raw), "society", [publisher], is_demo=True
        )
        save_article(conn, article, query="가상 야간 버스", raw=raw)
        text = (
            "이 기사는 직접 작성한 개발용 가상 자료입니다. 가상도시는 야간 버스 시범 운행을 발표했습니다. "
            "시범 운행은 2026년 10월 22일 가상도시에서 시작합니다. 야간 이동 선택지를 늘리기 위한 계획입니다. "
            "운영 비용과 실제 이용 수요는 시범 기간에 조사할 예정입니다. 구체적인 효과는 아직 확인되지 않았습니다. "
        ) * 2
        body = BodyImport(
            article_id=article.id,
            content_kind="full_text",
            text=text,
            source_kind="demo",
            source_url=article.canonical_url,
            acquired_at=datetime.now(timezone.utc),
            extractor_version="demo-v1",
            rights={
                "store": True,
                "cluster": True,
                "summarize": True,
                "analyze": True,
                "publish_summary": True,
                "display_full_text": index == 1,
                "evidence": "직접 작성한 가상 텍스트, 개발 검증용",
            },
        )
        save_body(conn, body)
        ids.append(str(article.id))
        body_items.append(body.model_dump(mode="json"))
    batch = export_batch(conn)
    # Scope the fixture result to these three articles, even if other data exists.
    claim = lambda text, refs=None: {"text": text, "article_ids": refs or ids[:2]}
    outputs = [
        {
            "mode": "summary",
            "status": "ready",
            "payload": {
                "title": "[가상] 야간 버스 시범 운행, 이동 선택지와 운영 과제",
                "bullets": [
                    claim("가상도시가 야간 버스 시범 운행을 시작합니다."),
                    claim("실제 이용 수요와 운영 비용은 추가 확인이 필요합니다."),
                ],
                "perspectives": [
                    {
                        "label": "이동 선택지",
                        "text": "야간 이동 기회를 늘리는 데 주목합니다.",
                        "article_ids": ids[:2],
                    },
                    {
                        "label": "운영 과제",
                        "text": "비용과 수요를 확인할 필요가 있습니다.",
                        "article_ids": ids[1:],
                    },
                ],
                "unknowns": ["실제 보도가 아닌 직접 작성한 가상 자료입니다."],
            },
        },
        {
            "mode": "five_w",
            "status": "ready",
            "payload": {
                "who": claim("가상도시"),
                "what": claim("야간 버스 시범 운행"),
                "when": claim("2026년 10월 22일"),
                "where": claim("가상도시"),
                "why": claim("야간 이동 선택지를 늘리기 위해"),
                "unknowns": ["시범 운행의 실제 효과는 아직 확인되지 않았습니다."],
            },
        },
        {
            "mode": "easy",
            "status": "ready",
            "payload": {
                "paragraphs": [
                    claim(
                        "밤늦게 집에 돌아갈 때 탈 수 있는 버스를 시험해 보는 이야기예요."
                    ),
                    claim(
                        "사람들이 얼마나 타는지, 돈이 얼마나 드는지는 더 알아봐야 해요."
                    ),
                ],
                "glossary": [
                    claim("시범 운행: 정식으로 시작하기 전에 시험 삼아 운영하는 것")
                ],
                "unknowns": ["직접 작성한 가상 설명입니다."],
            },
        },
        {
            "mode": "sentiment",
            "status": "ready",
            "payload": {
                "scope": "article_language",
                "observations": [
                    {
                        "article_id": key,
                        "label": "neutral",
                        "confidence": None,
                        "evidence": "구체적인 효과는 아직 확인되지 않았습니다.",
                    }
                    for key in ids
                ],
                "note": "화면 개발용 가상 결과입니다. 감정 모델을 실행한 결과가 아닙니다.",
            },
        },
    ]
    for output in outputs:
        output.update(
            model_version="demo-no-model-v1", prompt_version="demo-no-prompt-v1"
        )
    results = ResultBatch.model_validate(
        {
            "run_id": str(batch.run_id),
            "input_hash": batch.input_hash,
            "cluster_model_version": "demo-manual-grouping-v1",
            "clusters": [
                {
                    "event_key": "demo:night-bus:2026-10-22",
                    "article_ids": ids,
                    "same_event_verified": True,
                    "category": "society",
                    "outputs": outputs,
                }
            ],
        }
    )
    event_ids = import_results(conn, results)
    story = publish(
        conn,
        event_ids[0],
        reviewed=True,
        modes=("summary", "five_w", "easy", "sentiment"),
    )
    return {
        "story": story,
        "batch": batch,
        "results": results,
        "bodies": {"schema_version": "2.0", "items": body_items},
    }
