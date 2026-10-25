"""전달받은 가상 XML 4개를 변환합니다. HTTP/DB 작업은 하지 않습니다."""

import argparse
from collections import Counter
import json
from pathlib import Path

from .parser import FeedConfig, RIGHT_KEYS, parse_rss


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "rss" / "fixtures"
DEMO_CASES = (
    ("rss-title-only.xml", "feed-demo-economy", "publisher-demo-01", "가상 경제신문", "economy"),
    ("rss-no-and-media.xml", "feed-demo-industry", "publisher-demo-03", "가상 산업신문", "economy"),
    ("rss-dc-date.xml", "feed-demo-politics", "publisher-demo-02", "가상 지역신문", "politics"),
    ("rss-content-encoded.xml", "feed-demo-science", "publisher-demo-04", "가상 방송뉴스", "technology"),
)


def build_demo_items():
    # 직접 작성된 테스트 자료에만 쓰는 가정입니다. 실제 언론사의 허용 상태가 아닙니다.
    rights = dict.fromkeys(RIGHT_KEYS, "unknown")
    rights.update(collect="allowed", store="allowed")
    results = []
    for filename, feed_id, publisher_id, name, category in DEMO_CASES:
        feed = FeedConfig(feed_id, publisher_id, name, category, is_demo=True, rights=rights)
        results.extend(parse_rss((FIXTURE_DIR / filename).read_bytes(), feed=feed))
    return results


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, default=Path("work/rss_parser_result.json"))
    args = cli.parse_args()
    items = build_demo_items()
    records = [record for item in items if (record := item.to_record()) is not None]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = Counter(item.storage["parse_status"] for item in items)
    print(f"XML 파일: {len(DEMO_CASES)}, 파싱 항목: {len(items)}, JSON 항목: {len(records)}")
    print(f"parsed: {counts['parsed']}, partial: {counts['partial']}, error: {counts['error']}")
    for item in items:
        if item.storage["parse_issues"]:
            print(f"확인 사항: {item.storage['source_item_id']} / {item.storage['parse_issues']}")
    print(f"결과 파일: {args.output.resolve()}")


if __name__ == "__main__":
    main()
