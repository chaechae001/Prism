"""Behavior checks for the deliberately narrow, source-bound BOK extractor."""

from dataclasses import asdict
import importlib
import importlib.util
import json
from pathlib import Path
import unittest

from news_clustering.models import Article


def article(body=None, title="한은, 기준금리 연 3.0% 동결", published="2026-10-22T03:10:00Z"):
    return Article("synthetic", title, body if body is not None else
                   "한국은행이 오늘(22일) 금융통화위원회를 열고 기준금리를 연 3.00%로 동결했습니다.",
                   "경제", published)


class DecisionAnchorTests(unittest.TestCase):
    def setUp(self):
        name = "news_clustering.core.decision_anchors"
        self.assertIsNotNone(importlib.util.find_spec(name), "source-bound decision extractor is missing")
        module = importlib.import_module(name)
        self.extract = module.extract_bok_decision_anchor
        self.compare = module.compare_bok_decision_anchors

    def test_explicit_completed_decision_is_traceable_and_does_not_mutate_source(self):
        source = article()
        before = asdict(source)
        result = self.extract(source)
        self.assertTrue(result["supported"])
        self.assertEqual(result["institution"], "bank_of_korea")
        self.assertEqual(result["event_date"], "2026-10-22")
        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["rate_percent"], "3")
        self.assertEqual(result["source_content_hash"], source.content_hash)
        self.assertEqual(result["method"], "bok-primary-rate-decision/v1")
        self.assertIs(result["human_verified"], False)
        self.assertEqual(result["reasons"], [])
        self.assertEqual(asdict(source), before)
        self.assertTrue(result["evidence"])
        self.assertIn("오늘(22일)", [span["text"] for span in result["evidence"]])
        for span in result["evidence"]:
            self.assertIn(span["field"], ("title", "body"))
            raw = getattr(source, span["field"])
            self.assertEqual(raw[span["start"]:span["end"]], span["text"])
            self.assertGreater(span["end"], span["start"])

    def test_completed_attributed_and_explanation_forms(self):
        cases = [
            ("한국은행은 오늘(17일) 기준금리를 2.50%로 인하했습니다.", "한은 기준금리 인하", "cut", "2.5"),
            ("금통위는 오늘(17일) 기준금리를 연 4.25%로 인상하기로 결정했습니다.", "기준금리 인상", "raise", "4.25"),
            ("한국은행은 오늘(17일) 기준금리를 연 2.75%로 동결하는 데 모두 찬성했다고 공개했습니다.", "기준금리 동결", "hold", "2.75"),
            ("오늘(17일) 금통위가 기준금리를 동결했다고 밝혔습니다.", "금리 동결 배경", "hold", None),
        ]
        for body, title, action, rate in cases:
            with self.subTest(body=body):
                result = self.extract(article(body, title, "2027-02-17T01:00:00+00:00"))
                self.assertTrue(result["supported"], result)
                self.assertEqual((result["action"], result["rate_percent"], result["event_date"]),
                                 (action, rate, "2027-02-17"))

    def test_main_headline_wins_over_later_background_or_quote(self):
        for title in ("금리 동결 배경은? 금통위 ‘인상 영향 점검’", "한은 기준금리 동결…향후 인하 가능성", "금리 동결...연준 인상"):
            with self.subTest(title=title):
                result = self.extract(article(title=title))
                self.assertTrue(result["supported"], result)
                self.assertEqual(result["action"], "hold")

    def test_headline_requires_unambiguous_actual_primary_policy_action(self):
        titles = ["한은 기준금리 동결 전망", "기준금리 인하 예상", "기준금리 인상 가능성",
                  "기준금리 동결할까", "기준금리 동결 안 해", "금리 동결 또는 인상",
                  "은행 예금금리 동결", "주담대 금리 인하", "연준 금리 동결, 한은 주목",
                  "미국 기준금리 인하", "ECB 기준금리 동결", "기준금리 향방", "경제 전망…기준금리 동결"]
        for title in titles:
            with self.subTest(title=title):
                self.assertFalse(self.extract(article(title=title))["supported"])

    def test_body_requires_actual_bok_decision_not_forecast_negation_or_history(self):
        bodies = [
            "한국은행은 오늘(22일) 기준금리를 3%로 동결할 것으로 예상됩니다.",
            "한국은행은 오늘(22일) 기준금리 동결 가능성을 설명했습니다.",
            "한국은행은 오늘(22일) 기준금리를 동결하지 않았습니다.",
            "한국은행은 오늘(22일) 기준금리를 동결한 적이 없다고 밝혔습니다.",
            "한국은행은 오늘(22일) 회의를 열었습니다. 지난달 기준금리를 3%로 동결했습니다.",
            "한국은행은 오늘(22일) 기준금리 동결을 검토했습니다.",
            "한국은행은 오늘(22일) 내일 기준금리를 동결하기로 결정할 전망입니다.",
            "한국은행은 오늘(22일) 기준금리 동결에 대해 설명하지 않았습니다.",
            "한국은행 회의 사진. 오늘(22일) 연준은 기준금리를 3%로 동결했습니다.",
            "연준은 오늘(22일) 기준금리를 3%로 동결했습니다. 한국은행은 향후 대응을 검토합니다.",
            "오늘(22일) 시중은행은 예금금리를 3%로 동결했습니다.",
            "한국은행은 오늘(22일) 기준금리를 3%로 인상했습니다.",
            "한국은행은 오늘(22일) 오늘 동결한 것은 기준금리가 아니라 예금금리라고 설명했습니다.",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertFalse(self.extract(article(body))["supported"])

    def test_explicit_today_date_must_match_timezone_aware_korean_publication_day(self):
        for published in (None, "not-a-date", "2026-10-22T03:00:00", "2026-10-21T03:00:00Z"):
            with self.subTest(published=published):
                self.assertFalse(self.extract(article(published=published))["supported"])
        midnight = self.extract(article(published="2026-10-21T16:30:00Z"))
        self.assertTrue(midnight["supported"])
        self.assertEqual(midnight["event_date"], "2026-10-22")

    def test_plain_days_caption_dates_and_multiple_inconsistent_today_dates_do_not_establish_date(self):
        bodies = [
            "한국은행은 22일 기준금리를 3%로 동결했습니다.",
            "▲ 한국은행 총재가 22일 회의에 참석했다. 한국은행은 기준금리를 3%로 동결했습니다.",
            "한국은행은 오늘(21일) 기준금리를 3%로 동결했습니다.",
            "한국은행은 오늘(22일) 기준금리를 3%로 동결했습니다. 오늘(21일) 설명했습니다.",
            "한국은행은 기준금리를 3%로 동결했습니다. " + "가" * 700 + " 오늘(22일).",
        ]
        for body in bodies:
            with self.subTest(body=body[:90]):
                self.assertFalse(self.extract(article(body))["supported"])

    def test_body_decision_window_is_bounded_to_original_first_1200_characters(self):
        body = "한국은행은 오늘(22일) 회의를 열었습니다. " + "가" * 1200 + " 기준금리를 3%로 동결했습니다."
        self.assertFalse(self.extract(article(body))["supported"])

    def test_percent_point_change_and_unrelated_percent_are_never_target_rate(self):
        for body in ("한국은행은 오늘(22일) 기준금리를 0.25%포인트 인하했습니다.",
                     "한국은행은 오늘(22일) 기준금리를 0.25%p 인하했습니다.",
                     "한국은행은 오늘(22일) 기준금리를 동결했습니다. 물가는 3% 상승했습니다."):
            title = "기준금리 인하" if "인하" in body else "기준금리 동결"
            with self.subTest(body=body):
                result = self.extract(article(body, title))
                self.assertTrue(result["supported"], result)
                self.assertIsNone(result["rate_percent"])

    def test_distinct_explicit_target_levels_in_one_source_are_ambiguous(self):
        result = self.extract(article(title="한은 기준금리 연 3.25% 동결"))
        self.assertFalse(result["supported"])
        self.assertIn("ambiguous_target_rate", result["reasons"])

    def test_transition_headline_cannot_supply_prior_rate_as_target(self):
        body = "한국은행은 오늘(22일) 기준금리를 인하했습니다."
        for title in ("한은 기준금리 3.0%→2.75% 인하", "한은 기준금리 3.0%에서 2.75%로 인하"):
            with self.subTest(title=title):
                result = self.extract(article(body, title))
                self.assertFalse(result["supported"])
                self.assertIsNone(result["rate_percent"])

    def test_today_metadata_cannot_date_a_decision_in_a_different_sentence(self):
        bodies = [
            "오늘(22일) 시장 동향입니다. 한국은행은 21일 기준금리를 동결했습니다.",
            "오늘(22일) 보고서입니다. 한국은행은 2025년 10월 22일 기준금리를 동결했습니다.",
            "한국은행은 오늘(22일) 회의를 열었습니다. 한국은행은 기준금리를 동결했습니다.",
            "한국은행은 오늘(22일) 기준금리 동결 배경을 밝혔습니다. 한국은행은 기준금리를 동결했습니다.",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertFalse(self.extract(article(body))["supported"])

    def test_conflicting_relative_or_explicit_decision_prefix_date_fails_closed(self):
        prefixes = ["어제", "그제", "내일", "21일", "2025년 10월 22일", "9월 22일", "지난해", "지난 9월"]
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                body = f"한국은행은 오늘(22일) {prefix} 기준금리를 동결했다고 밝혔습니다."
                self.assertFalse(self.extract(article(body))["supported"])

    def test_corrected_or_retracted_completed_report_is_not_decision_evidence(self):
        for ending in ("오보를 정정했습니다", "허위 보도를 부인했습니다", "보도를 철회했습니다", "거짓 주장을 반박했습니다"):
            with self.subTest(ending=ending):
                body = f"한국은행은 오늘(22일) 기준금리를 동결했다는 {ending}."
                self.assertFalse(self.extract(article(body))["supported"])

    def test_unknown_foreign_actor_cannot_borrow_bok_from_prior_sentence(self):
        for body in ("한국은행은 오늘(22일) 보고서를 냈습니다. 호주중앙은행은 기준금리를 동결했습니다.",
                     "한국은행은 보고서를 냈습니다. 호주중앙은행은 오늘(22일) 기준금리를 동결했습니다.",
                     "한국은행은 오늘(22일) 보고서를 냈습니다. 기준금리를 동결했습니다."):
            with self.subTest(body=body):
                self.assertFalse(self.extract(article(body))["supported"])

    def test_sentence_binding_holds_without_spaces_and_after_closing_quotes(self):
        for body in ("한국은행은 오늘(22일) 보고서를 냈습니다.호주중앙은행은 기준금리를 동결했습니다.",
                     "오늘(22일) 시장 동향입니다.한국은행은 2025년 10월 22일 기준금리를 동결했습니다.",
                     '한국은행은 오늘(22일) "보고서를 냈습니다." 호주중앙은행은 기준금리를 동결했습니다.'):
            with self.subTest(body=body):
                self.assertFalse(self.extract(article(body))["supported"])

    def test_historical_or_future_primary_headline_is_not_current_decision(self):
        for title in ("한은, 지난해 기준금리 동결", "한은, 지난달 기준금리 동결", "한은 연내 기준금리 인하",
                      "한은 내년 기준금리 인하", "한은 내일 기준금리 동결", "한은 2025년 10월 22일 기준금리 동결"):
            with self.subTest(title=title):
                action = "인하" if "인하" in title else "동결"
                self.assertFalse(self.extract(article(f"한국은행은 오늘(22일) 기준금리를 {action}했습니다.", title))["supported"])

    def test_canonical_rate_comparison_and_missing_rate(self):
        a = self.extract(article())
        b = self.extract(article("한국은행은 오늘(22일) 기준금리를 연 3.0%로 동결했습니다."))
        c = self.extract(article("한국은행은 오늘(22일) 기준금리를 동결했습니다.", "금리 동결 배경"))
        for right in (b, c):
            comparison = self.compare(a, right)
            self.assertTrue(comparison["compatible"], comparison)
            self.assertEqual(comparison["conflicts"], [])
            self.assertIs(comparison["human_verified"], False)

    def test_explicit_conflicts_block_compatibility(self):
        left = self.extract(article())
        for field, value in (("rate_percent", "3.25"), ("action", "raise"),
                             ("event_date", "2026-11-22"), ("institution", "federal_reserve")):
            with self.subTest(field=field):
                right = {**left, field: value}
                result = self.compare(left, right)
                self.assertFalse(result["compatible"])
                self.assertIn(field, result["conflicts"])

    def test_unknown_anchor_is_incompatible_but_missing_information_is_not_conflict(self):
        left = self.extract(article())
        right = self.extract(article("경제 전망에 대한 보도입니다.", "경제 전망"))
        result = self.compare(left, right)
        self.assertFalse(result["compatible"])
        self.assertEqual(result["conflicts"], [])
        self.assertIsNone(right["institution"])
        self.assertIsNone(right["action"])
        self.assertIsNone(right["event_date"])

    def test_denied_or_hypothetical_quoted_completion_is_not_actual_decision(self):
        bodies = [
            "한국은행은 오늘(22일) 기준금리를 동결했다는 전망이 나왔습니다.",
            "한국은행은 오늘(22일) 기준금리를 동결했습니다라는 보도는 사실이 아니라고 밝혔습니다.",
            "한국은행은 오늘(22일) 기준금리 동결에 대해 설명했을 것이라고 예상했습니다.",
            "한국은행은 오늘(22일) 기준금리를 동결했다고 밝히지 않았습니다.",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertFalse(self.extract(article(body))["supported"])

    def test_decision_does_not_borrow_institution_across_foreign_primary_subject(self):
        body = "한국은행은 오늘(22일) 보고서를 냈습니다. 연준이 회의를 열었습니다. 기준금리를 동결했습니다."
        self.assertFalse(self.extract(article(body))["supported"])

    def test_conditional_and_scheduled_future_completed_wording_is_not_actual(self):
        bodies = [
            "한국은행은 오늘(22일) 기준금리를 동결했다면 시장이 안정됐을 것이라고 설명했습니다.",
            "한국은행은 오늘(22일) 기준금리를 동결한 뒤 기자간담회를 열 예정입니다.",
            "한국은행은 오늘(22일) 기준금리 동결에 대해 설명한 경우를 가정했습니다.",
            "한국은행은 오늘(22일) 기준금리 동결에 대해 설명했으면 좋겠다는 요청을 받았습니다.",
            "한국은행은 오늘(22일) 기준금리를 동결할 수 있다고 밝혔습니다.",
            "한국은행은 오늘(22일) 기준금리를 동결한다고 예상했습니다.",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertFalse(self.extract(article(body))["supported"])

    def test_incomplete_or_other_method_dicts_do_not_claim_compatibility(self):
        left = self.extract(article())
        for right in ({"supported": True}, {**left, "action": None}, {**left, "method": "other"}):
            with self.subTest(right=right):
                result = self.compare(left, right)
                self.assertFalse(result["compatible"])
                self.assertEqual(result["conflicts"], [])

    def test_actual_completion_must_consume_sentence_without_claim_or_conjecture_tail(self):
        for ending in ("했다는 주장을 일축했습니다", "했다는 주장이 제기됐습니다", "했다고 추측했습니다",
                       "했다는 소문을 전했습니다", '했습니다\"라는 주장은 근거가 없다고 말했습니다'):
            with self.subTest(ending=ending):
                body = "한국은행은 오늘(22일) 기준금리를 동결" + ending + "."
                self.assertFalse(self.extract(article(body))["supported"])

    def test_generic_other_bank_actor_in_title_or_decision_sentence_is_unsupported(self):
        for bank in ("호주중앙은행", "뉴질랜드준비은행", "남부은행", "아무 중앙은행"):
            with self.subTest(bank=bank):
                self.assertFalse(self.extract(article(title=f"{bank} 기준금리 동결"))["supported"])
                body = f"한국은행에 따르면 오늘(22일) {bank}은 기준금리를 동결했습니다."
                self.assertFalse(self.extract(article(body))["supported"])
                body = f"한국은행은 오늘(22일) {bank}이 기준금리를 동결했다고 밝혔습니다."
                self.assertFalse(self.extract(article(body))["supported"])

    def test_bok_mention_does_not_replace_explicit_bok_decision_subject(self):
        for body in ("한국은행에 따르면 오늘(22일) 기준금리를 동결했습니다.",
                     "오늘(22일) 한국은행 보고서는 기준금리를 동결했다고 밝혔습니다."):
            with self.subTest(body=body):
                self.assertFalse(self.extract(article(body))["supported"])

    def test_explanation_or_afterward_wording_alone_cannot_date_actual_decision(self):
        bodies = [
            "한국은행 총재는 오늘(22일) 기준금리 동결에 대해 설명했습니다.",
            "한국은행은 오늘(22일) 기준금리 동결에 대해 지난달 결정 배경을 설명했습니다.",
            "한국은행 총재는 오늘(22일) 기준금리 동결에 대해 지난달 결정을 설명했습니다.",
            "한국은행은 오늘(22일) 기준금리를 동결한 뒤 이튿날 금리를 올렸다는 지난해 상황을 설명했습니다.",
            "오늘(22일) 금융통화위원회가 기준금리를 동결한 뒤 기자간담회를 열었습니다.",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertFalse(self.extract(article(body))["supported"])

    def test_explanation_requires_traceable_same_day_committee_confirmation(self):
        explanation = "한국은행 총재는 오늘(22일) 기준금리 동결에 대해 지난 5·6월 연속 인상으로 인해 그만큼 금리 인상 속도를 조절할 시간을 번 결과라고 설명했습니다."
        confirmation = '총재는 이날 오전 금융통화위원회가 기준금리를 동결한 뒤 연 기자간담회에서 "경제 여건을 고려한 결과"라고 말했습니다.'
        source = article(explanation + " " + confirmation, "총재 ‘금리 동결 배경’")
        result = self.extract(source)
        self.assertTrue(result["supported"], result)
        self.assertEqual(result["event_date"], "2026-10-22")
        self.assertIsNone(result["rate_percent"])
        self.assertIn(confirmation[:-1], [span["text"] for span in result["evidence"]])
        self.assertIn("이날", [span["text"] for span in result["evidence"]])
        self.assertIn("금융통화위원회", [span["text"] for span in result["evidence"]])
        for span in result["evidence"]:
            self.assertEqual(getattr(source, span["field"])[span["start"]:span["end"]], span["text"])

    def test_explanation_confirmation_cannot_be_past_other_actor_or_other_action(self):
        explanation = "한국은행 총재는 오늘(22일) 기준금리 동결에 대해 설명했습니다. "
        for clause in ("어제 오전 금융통화위원회가 기준금리를 동결한 뒤", "이날 오전 호주중앙은행이 기준금리를 동결한 뒤",
                       "이날 오전 금융통화위원회가 기준금리를 인상한 뒤", "이날 오전 금융통화위원회가 기준금리를 동결했다고 추측한 뒤"):
            with self.subTest(clause=clause):
                body = explanation + f'총재는 {clause} 연 기자간담회에서 "경제 여건을 고려했다"고 말했습니다.'
                self.assertFalse(self.extract(article(body, "금리 동결 배경"))["supported"])

    def test_same_day_followup_cannot_skip_an_intervening_different_date(self):
        explanation = "한국은행 총재는 오늘(22일) 기준금리 동결에 대해 설명했습니다. "
        confirmation = '총재는 이날 오전 금융통화위원회가 기준금리를 동결한 뒤 연 기자간담회에서 "경제 여건을 고려했다"고 말했습니다.'
        for intervening in ("어제 회의를 개최했습니다. ", "2025년 10월 22일 회의에 참석했습니다. ", "지난달 기자간담회를 열었습니다. "):
            with self.subTest(intervening=intervening):
                body = explanation + intervening + confirmation
                self.assertFalse(self.extract(article(body, "금리 동결 배경"))["supported"])

    def test_same_day_confirmation_cannot_override_historical_time_in_explanation(self):
        confirmation = '총재는 이날 금융통화위원회가 기준금리를 동결한 뒤 연 기자간담회에서 "결정은 적절했습니다"라고 말했습니다.'
        for reason in ("지난달 22일의 결정을", "지난달 결정을", "지난해 동결을", "지난달 22일 결정을",
                       "2025년 10월 22일 결정을", "어제 동결한 이유를", "전월 결정을", "당시 동결 결정을"):
            with self.subTest(reason=reason):
                explanation = f"한국은행 총재는 오늘(23일) 기준금리 동결에 대해 {reason} 설명했습니다. "
                result = self.extract(article(explanation + confirmation, "한은 기준금리 동결", "2026-10-23T09:00:00+09:00"))
                self.assertFalse(result["supported"])
                self.assertIsNone(result["event_date"])

    def test_causal_background_must_be_a_different_action_and_have_no_unresolved_time(self):
        confirmation = '총재는 이날 금융통화위원회가 기준금리를 동결한 뒤 연 기자간담회에서 "결정은 적절했습니다"라고 말했습니다.'
        reasons = [
            "지난 5·6월 연속 동결로 인해 그만큼 금리 동결 속도를 조절할 시간을 번 결과라고",
            "지난 5·6월 22일 연속 인상으로 인해 시간을 번 결과라고",
            "지난 5·6월 연속 인상으로 인해 지난해 결정을 설명할 시간을 번 결과라고",
            "지난 5·6월 연속 인상으로 인해 이튿날 동결한 결과라고",
            "지난달 결정으로 인해 시간을 번 결과라고",
        ]
        for reason in reasons:
            with self.subTest(reason=reason):
                explanation = f"한국은행 총재는 오늘(23일) 기준금리 동결에 대해 {reason} 설명했습니다. "
                self.assertFalse(self.extract(article(explanation + confirmation, "한은 기준금리 동결", "2026-10-23T09:00:00+09:00"))["supported"])

    def test_generic_different_action_causal_history_can_support_confirmed_current_decision(self):
        explanation = "한국은행 총재는 오늘(14일) 기준금리 인하에 대해 지난 2·3월 연속 동결로 인해 그만큼 금리 동결 속도를 조절할 시간을 번 결과라고 설명했습니다. "
        confirmation = '총재는 이날 오전 금통위가 기준금리를 인하한 뒤 연 기자간담회에서 "경제 여건을 고려했습니다"라고 말했습니다.'
        source = article(explanation + confirmation, "한은 기준금리 인하", "2028-09-14T01:00:00Z")
        result = self.extract(source)
        self.assertTrue(result["supported"], result)
        self.assertEqual((result["action"], result["event_date"], result["rate_percent"]), ("cut", "2028-09-14", None))
        for span in result["evidence"]:
            self.assertEqual(getattr(source, span["field"])[span["start"]:span["end"]], span["text"])

    def test_inspected_source_examples_require_same_sentence_today_and_actor(self):
        path = Path(__file__).resolve().parents[1] / "data/experiments/seed-neighbours-20261023/runs/combined/multiview-group/input.json"
        if not path.exists():
            self.skipTest("local development source fixture unavailable")
        ids = ("article-8de9e4368121dfc760b81481", "article-9d91920409131c0e66a8da04", "article-c7d929010656461b6faa2c46")
        sources = {item["article_id"]: Article.from_dict(item) for item in json.loads(path.read_text(encoding="utf-8"))["articles"]}
        anchors = [self.extract(sources[article_id]) for article_id in ids]
        # The official-statement article has today in an earlier sentence, so
        # this narrow recognizer deliberately declines to date its decision.
        self.assertEqual([anchor["supported"] for anchor in anchors], [False, True, True])
        self.assertEqual([anchor["rate_percent"] for anchor in anchors], [None, "3", None])
        for article_id, anchor in zip(ids, anchors):
            self.assertEqual(anchor["event_date"], "2026-10-22" if anchor["supported"] else None)
            for span in anchor["evidence"]:
                self.assertEqual(getattr(sources[article_id], span["field"])[span["start"]:span["end"]], span["text"])
        self.assertTrue(self.compare(anchors[1], anchors[2])["compatible"])
        self.assertFalse(self.compare(anchors[0], anchors[1])["compatible"])


if __name__ == "__main__":
    unittest.main()
