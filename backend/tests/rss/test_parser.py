"""네트워크와 DB 없이 실행하는 RSS 입력 계약 테스트."""

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from backend.app.rss.parser import (
    FeedConfig, MAX_XML_BYTES, RSSParseError, canonicalize_url, parse_rss,
)


FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc)


def xml_item(fields):
    return f'<rss version="2.0"><channel><item>{fields}</item></channel></rss>'


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.feed = FeedConfig("test-feed", "test-publisher", "가상 신문", "economy", True)

    def parse(self, xml, feed=None, at=NOW):
        return parse_rss(xml, feed=feed or self.feed, collected_at=at)

    def fixture(self, filename):
        return self.parse((FIXTURES / filename).read_bytes())

    def test_title_only_does_not_invent_content(self):
        item = self.fixture("rss-title-only.xml")[0]
        record = item.to_record()
        self.assertEqual(record["parse_status"], "parsed")
        self.assertEqual(record["body_status"], "not_provided")
        self.assertIsNone(record["author"])
        self.assertIsNone(record["rss_description"])
        self.assertIsNone(item.storage["content_html"])
        self.assertEqual(item.storage["media"], [])
        self.assertEqual(record["published_at"], "2026-10-22T00:00:00+00:00")

    def test_original_url_preserved_while_utm_removed(self):
        record = self.fixture("rss-title-only.xml")[0].to_record()
        self.assertTrue(record["original_url"].endswith("?utm_source=demo"))
        self.assertEqual(record["canonical_url"], "https://example.com/demo/rss-001")
        self.assertTrue(record["item_key"].startswith("url-v1:"))

    def test_no_identifier_and_media_attributes(self):
        item = self.fixture("rss-no-and-media.xml")[0]
        record = item.to_record()
        self.assertEqual(record["source_item_id"], "demo-003")
        self.assertEqual(record["item_key"], "no-v1:demo-003")
        self.assertEqual(record["source_category"], "산업")
        self.assertEqual(record["category"], "economy")
        self.assertEqual(record["author"], "가상 기자")
        self.assertEqual(item.storage["media"][0]["type"], "image/jpeg")
        self.assertEqual(item.storage["media"][0]["url"], "https://example.com/demo/image-003.jpg")

    def test_invalid_dc_date_preserved_and_not_replaced(self):
        item = self.fixture("rss-dc-date.xml")[0]
        self.assertEqual(item.storage["source_published_raw"], "not-a-date")
        self.assertIsNone(item.to_record()["published_at"])
        self.assertEqual(item.storage["parse_issues"], ["invalid_published_at"])
        self.assertEqual(item.to_record()["parse_status"], "partial")
        self.assertEqual(item.to_record()["author"], "가상 기자")

    def test_valid_dc_date_and_creator(self):
        record = self.fixture("rss-dc-date.xml")[1].to_record()
        self.assertEqual(record["published_at"], "2026-10-22T00:07:00+00:00")
        self.assertEqual(record["parse_status"], "parsed")
        self.assertEqual(record["body_status"], "not_provided")

    def test_content_and_media_kept_out_of_common_json(self):
        item = self.fixture("rss-content-encoded.xml")[0]
        self.assertEqual(item.storage["content_html"], "<p>직접 작성한 HTML 콘텐츠입니다.</p>")
        self.assertEqual(len(item.storage["media"]), 2)
        self.assertEqual(item.storage["media"][1]["length"], "0")
        self.assertEqual(item.to_record()["body_status"], "content_available")
        self.assertNotIn("content_html", item.to_record())
        self.assertNotIn("media", item.to_record())

    def test_all_five_records_match_contract_keys_types_and_enums(self):
        schema = json.loads((FIXTURES / "normalized.schema.json").read_text(encoding="utf-8"))
        records = [item.to_record() for file in sorted(FIXTURES.glob("*.xml")) for item in self.parse(file.read_bytes())]
        self.assertEqual(len(records), 5)
        for record in records:
            self.assertEqual(set(record), set(schema["required"]))
            for key, spec in schema["properties"].items():
                value = record[key]
                if "const" in spec:
                    self.assertEqual(value, spec["const"])
                if "enum" in spec:
                    self.assertIn(value, spec["enum"])
                if "type" in spec:
                    kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
                    expected = {"string": str, "null": type(None), "boolean": bool, "object": dict}
                    self.assertIn(type(value), [expected[kind] for kind in kinds])
                if spec.get("minLength"):
                    self.assertTrue(value)
                if spec.get("format") == "date-time" and value is not None:
                    self.assertIsNotNone(datetime.fromisoformat(value).utcoffset())
                if spec.get("format") == "uri":
                    self.assertTrue(value.startswith(("http://", "https://")))
            self.assertEqual(set(record["rights"]), set(schema["properties"]["rights"]["required"]))
            for value in record["rights"].values():
                self.assertIn(value, schema["$defs"]["right"]["enum"])
            self.assertTrue(record["is_demo"])

    def test_stable_id_on_repeat_collection_and_tracking_change(self):
        first = self.fixture("rss-title-only.xml")[0]
        xml = (FIXTURES / "rss-title-only.xml").read_text(encoding="utf-8").replace("utm_source=demo", "utm_source=other")
        later = self.parse(xml, at=datetime(2026, 10, 23, tzinfo=timezone.utc))[0]
        self.assertEqual(first.storage["id"], later.storage["id"])
        self.assertEqual(first.storage["item_key"], later.storage["item_key"])
        self.assertNotEqual(first.storage["collected_at"], later.storage["collected_at"])

    def test_same_article_from_different_feeds_has_different_id(self):
        xml = (FIXTURES / "rss-title-only.xml").read_bytes()
        first = self.parse(xml)[0].storage
        other = self.parse(xml, feed=replace(self.feed, feed_id="other-feed"))[0].storage
        self.assertNotEqual(first["id"], other["id"])
        self.assertEqual(first["canonical_url"], other["canonical_url"])

    def test_article_queries_remain_distinct(self):
        self.assertEqual(canonicalize_url("https://Example.com:443/read?id=123&utm_source=x&token=a%2Fb#top"), "https://example.com/read?id=123&token=a%2Fb")
        self.assertNotEqual(canonicalize_url("https://example.com/?id=1"), canonicalize_url("https://example.com/?id=2"))

    def test_guid_takes_priority_over_no(self):
        item = self.parse(xml_item("<guid>abc</guid><no>123</no><title>제목</title><link>https://example.com/a</link>"))[0]
        self.assertEqual(item.storage["item_key"], "guid-v1:abc")

    def test_missing_or_invalid_required_fields_are_internal_errors(self):
        cases = ["<title>제목</title>", "<link>https://example.com/a</link>", "<title>제목</title><link>javascript:alert(1)</link>"]
        for fields in cases:
            with self.subTest(fields=fields):
                item = self.parse(xml_item(fields))[0]
                self.assertEqual(item.storage["parse_status"], "error")
                self.assertIsNone(item.to_record())
                self.assertIn("<item>", item.storage["raw_item_xml"])
                self.assertTrue(item.storage["id"])

    def test_valid_neighbor_survives_invalid_item(self):
        xml = '<rss version="2.0"><channel><item/><item><title>제목</title><link>https://example.com/a</link></item></channel></rss>'
        items = self.parse(xml)
        self.assertEqual(len(items), 2)
        self.assertIsNone(items[0].to_record())
        self.assertIsNotNone(items[1].to_record())

    def test_missing_date_and_timezone_are_partial(self):
        base = "<title>제목</title><link>https://example.com/a</link>"
        for date, issue in [("", "missing_published_at"), ("<pubDate>2026-10-22T09:00:00</pubDate>", "missing_published_timezone")]:
            item = self.parse(xml_item(base + date))[0]
            self.assertIsNone(item.storage["published_at"])
            self.assertEqual(item.storage["parse_status"], "partial")
            self.assertIn(issue, item.storage["parse_issues"])

    def test_unknown_rights_preserved_and_denied_marks_blocked(self):
        record = self.fixture("rss-content-encoded.xml")[0].to_record()
        self.assertTrue(all(value == "unknown" for value in record["rights"].values()))
        feed = replace(self.feed, rights={**self.feed.rights, "store": "denied"})
        item = self.parse((FIXTURES / "rss-content-encoded.xml").read_bytes(), feed=feed)[0]
        self.assertEqual(item.to_record()["body_status"], "blocked")

    def test_invalid_feed_settings_fail_before_parse(self):
        for changes in ({"default_category": "산업"}, {"rights": {"collect": "allowed"}}, {"is_demo": "true"}, {"feed_id": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.feed, **changes)

    def test_document_errors_raise_instead_of_returning_empty_list(self):
        for xml in ("<rss", "<rss version='2.0'/>", "<feed/>", "<!DOCTYPE rss [<!ENTITY x 'test'>]><rss version='2.0'><channel/></rss>"):
            with self.subTest(xml=xml), self.assertRaises(RSSParseError):
                self.parse(xml)

    def test_valid_empty_feed_returns_empty_list(self):
        self.assertEqual(self.parse('<rss version="2.0"><channel/></rss>'), [])

    def test_size_and_unsupported_encoding_rejected(self):
        for xml in (" " * (MAX_XML_BYTES + 1), b"\xff", '<?xml version="1.0" encoding="euc-kr"?><rss version="2.0"><channel/></rss>'):
            with self.assertRaises(RSSParseError):
                self.parse(xml)

    def test_collected_time_requires_timezone(self):
        with self.assertRaises(ValueError):
            self.parse('<rss version="2.0"><channel/></rss>', at=datetime(2026, 10, 22))


if __name__ == "__main__":
    unittest.main()
