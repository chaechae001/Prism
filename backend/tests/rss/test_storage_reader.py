"""DB 접속 없이 실행하는 입력 검증·오류 전달·출력 형식 테스트."""

from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock, Mock

from backend.app.rss.parser import FeedConfig, parse_rss
from backend.app.rss.reader import RSSReader, _record
from backend.app.rss.storage import RSSStorageError, _timestamp, save_feed_items


class ReaderStorageTests(unittest.TestCase):
    def test_reader_list_does_not_hide_database_failure(self):
        engine = Mock()
        engine.connect.side_effect = RuntimeError("테스트 DB 실패")
        with self.assertRaisesRegex(RuntimeError, "테스트 DB 실패"):
            RSSReader(engine).list_records()

    def test_reader_detail_does_not_hide_database_failure(self):
        engine = Mock()
        engine.connect.side_effect = RuntimeError("테스트 DB 실패")
        with self.assertRaisesRegex(RuntimeError, "테스트 DB 실패"):
            RSSReader(engine).get_record("rss-test")

    def test_invalid_limits_rejected_before_database_access(self):
        engine = Mock()
        for limit in (0, -1, 101, True, "10", None):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                RSSReader(engine).list_records(limit)
        engine.connect.assert_not_called()

    def test_empty_record_id_rejected_before_database_access(self):
        engine = Mock()
        for record_id in ("", " ", None, 1):
            with self.subTest(record_id=record_id), self.assertRaises(ValueError):
                RSSReader(engine).get_record(record_id)
        engine.connect.assert_not_called()

    def test_successful_empty_list_and_missing_detail(self):
        engine = MagicMock()
        connection = engine.connect.return_value.__enter__.return_value
        connection.execute.return_value.mappings.return_value.all.return_value = []
        connection.execute.return_value.mappings.return_value.first.return_value = None
        self.assertEqual(RSSReader(engine).list_records(), [])
        self.assertIsNone(RSSReader(engine).get_record("missing"))

    def test_record_uses_contract_keys_and_timezone(self):
        feed = FeedConfig("test-feed", "test-publisher", "가상 신문", "economy", True)
        item = parse_rss('<rss version="2.0"><channel><item><title>제목</title><link>https://example.com/a</link></item></channel></rss>', feed=feed)[0]
        row = {**item.storage, "publisher_id": feed.publisher_id, "publisher_name": feed.publisher_name}
        row["collected_at"] = datetime(2026, 10, 22, tzinfo=timezone.utc)
        record = _record(row)
        self.assertEqual(set(record), set(item.to_record()))
        self.assertEqual(record["collected_at"], "2026-10-22T00:00:00+00:00")
        self.assertIsNone(record["published_at"])
        self.assertNotIn("raw_item_xml", record)
        self.assertNotIn("content_html", record)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(RSSStorageError):
            _timestamp(datetime(2026, 10, 22))

    def test_mixed_feed_batch_rejected_before_database_access(self):
        feed = FeedConfig("other", "publisher", "가상 신문", "economy", True)
        item = parse_rss('<rss version="2.0"><channel><item/></channel></rss>', feed=feed)[0]
        engine = Mock()
        with self.assertRaises(RSSStorageError):
            save_feed_items("expected", [item], engine=engine)
        engine.begin.assert_not_called()

    def test_storage_database_failure_is_not_success(self):
        engine = Mock()
        engine.begin.side_effect = RuntimeError("테스트 DB 실패")
        with self.assertRaisesRegex(RuntimeError, "테스트 DB 실패"):
            save_feed_items("test", [], engine=engine)


if __name__ == "__main__":
    unittest.main()
