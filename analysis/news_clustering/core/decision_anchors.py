"""Conservative, deterministic anchors for explicitly reported BOK decisions.

This is a small Korean phrase recognizer, not general event extraction or NER.
It only supports a decision declared in the main headline and corroborated by
complete, narrow Korean assertion templates in the original lead. Direct
assertions require an explicit BOK subject and today/day in the same sentence.
An explanation requires a second, explicit same-day committee/press-conference
confirmation; explanation wording alone cannot date the decision. Explanation
reasons support only a neutral sentence or a bounded causal template describing
earlier monthly moves of a different action. Unresolved historical reasons and
other wording abstain, even with a valid-looking same-day follow-up. Evidence
offsets index the supplied Article strings.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
from typing import Any

from news_clustering.models import Article


_METHOD = "bok-primary-rate-decision/v1"
_KST = timezone(timedelta(hours=9))
_ACTION = {"동결": "hold", "인상": "raise", "인하": "cut"}
_NAMED_BANK = re.compile(r"[가-힣A-Za-z·]*은행")
_OTHER_INSTITUTION = re.compile(r"연준|연방준비|\bFed\b|\bFOMC\b|\bECB\b|유럽중앙은행|일본은행|영란은행|미국|일본|중국|시중은행", re.I)
_RETAIL = re.compile(r"예금|적금|대출|주담대|주택담보|은행권|시중은행")
_PROJECTION = re.compile(
    r"전망|예상|가능성|관측|예고|검토|할까|할지|할\s*것|하겠|해야|할\s*필요|"
    r"하지|아니|않|못|불발|미정|추진|안\s*해|예정|계획|다면|라면|으면|경우|가정|시나리오|촉구|요청|요구|"
    r"오보|정정|철회|취소|허위|부인|반박|거짓|왜곡|번복|사실무근"
)
_TODAY = re.compile(r"오늘\s*[（(]\s*(?:(?P<month>\d{1,2})\s*월\s*)?(?P<day>\d{1,2})\s*일\s*[)）]")
_TODAY_TEXT = r"오늘\s*[（(]\s*(?:\d{1,2}\s*월\s*)?\d{1,2}\s*일\s*[)）]"
_BOK_SUBJECT = r"(?P<institution>한국은행|한은|금융통화위원회|금통위)(?:은|는|이|가)"
_DIRECT_PREFIX = re.compile(
    rf"\s*(?:{_TODAY_TEXT}\s*)?{_BOK_SUBJECT}\s*(?:{_TODAY_TEXT}\s*)?"
    r"(?:(?:금융통화위원회|금통위)(?:를|을)\s*열고\s*)?"
)
_NUMBER = r"\d+(?:\.\d+)?"
_TARGET = re.compile(rf"기준금리(?:를|는|가)?\s*(?:연\s*)?(?P<rate>{_NUMBER})\s*%(?!\s*(?:포인트|[pP]))\s*로?")
_POLICY_ACTION = re.compile(
    rf"기준금리(?:를|는|가)?\s*(?:연\s*)?"
    rf"(?:(?:{_NUMBER}\s*%(?:\s*(?:포인트|[pP])(?:씩)?|\s*로))\s*)?"
    r"(?P<action>동결|인상|인하)"
)
_DIRECT_END = re.compile(
    r"(?:했(?:습니다|다)|하였(?:습니다|다)|"
    r"했다고\s*(?:밝혔|발표했|설명했)(?:습니다|다)|"
    r"하기로\s*(?:결정|의결)했(?:습니다|다)|"
    r"하는\s*데\s*모두\s*찬성했다고\s*공개했습니다|"
    r"을\s*(?:결정|의결)했(?:습니다|다))\s*[\"'”’」』]*\s*"
)
_EXPLANATION_PREFIX = re.compile(
    rf"\s*(?:[가-힣A-Za-z·]+\s+)?(?P<institution>한국은행|한은)\s*총재(?:는|가)\s*{_TODAY_TEXT}\s*"
)
_EXPLANATION_END = re.compile(r"에\s*대해\s*설명했습니다\s*[\"'”’」』]*\s*")
_CAUSAL_EXPLANATION_END = re.compile(
    r"에\s*대해\s*지난\s*(?P<months>\d{1,2}(?:\s*[·,]\s*\d{1,2})*)\s*월\s*연속\s*"
    r"(?P<background_action>동결|인상|인하)(?:으로|로)\s*인해\s*(?:그만큼\s*)?"
    r"(?:금리\s*(?P<effect_action>동결|인상|인하)\s*속도를\s*조절할\s*)?"
    r"시간을\s*번\s*결과라고\s*설명했습니다\s*[\"'”’」』]*\s*"
)
_CONFIRMATION = re.compile(
    r"\s*(?:[가-힣A-Za-z·]+\s+)?(?:한국은행\s*총재|한은\s*총재|총재)는\s*"
    r"(?P<same_day>이\s*날)\s*(?:오전|오후)?\s*"
    r"(?P<institution>금융통화위원회|금통위)가\s*"
    rf"(?P<policy>{_POLICY_ACTION.pattern})한\s*뒤\s*연\s*기자간담회에서\s*"
    r"[\"“][^\"”\n]*[\"”](?:이라고|라고|고)\s*말했습니다\s*[\"'”’」』]*\s*"
)
_HISTORICAL_PREFIX = re.compile(r"지난(?:달|해|주|\s*\d+\s*(?:월|일))|과거|당시|작년|전년")
_OTHER_TIME = re.compile(r"어제|그제|내일|모레|내년|내달|연내|향후|다음\s*(?:달|주|해)")
_CALENDAR_PART = re.compile(r"(?P<year>\d{4})\s*년|(?P<month>\d{1,2})\s*월|(?P<day>\d{1,2})\s*일")


def _evidence(field: str, raw: str, start: int, end: int) -> dict[str, Any]:
    return {"field": field, "start": start, "end": end, "text": raw[start:end]}


def _canonical_rate(value: str) -> str:
    return format(Decimal(value).normalize(), "f")


def _has_other_named_bank(raw: str) -> bool:
    """Reject competing bank subjects structurally, without a country list."""
    return any(match.group() != "한국은행" for match in _NAMED_BANK.finditer(raw))


def _conflicting_calendar_date(raw: str, local_date) -> bool:
    """All explicit date components must agree with the asserted today date."""
    return any(int(match[name]) != getattr(local_date, name)
               for match in _CALENDAR_PART.finditer(raw)
               for name in ("year", "month", "day") if match[name] is not None)


def _sentences(raw: str):
    """Yield raw spans, including boundaries with no space or a closing quote."""
    start = 0
    # A period between digits belongs to a decimal, not a sentence boundary.
    for delimiter in re.finditer(r"(?:[!?。]|(?<!\d)\.|\.(?!\d))[\"'”’」』]*\s*|\n+", raw):
        if start < delimiter.start():
            yield start, delimiter.start(), raw[start:delimiter.start()]
        start = delimiter.end()
    if start < len(raw):
        yield start, len(raw), raw[start:]


def extract_bok_decision_anchor(article: Article) -> dict[str, Any]:
    """Recognize only source-explicit completed BOK primary-rate decisions.

    Unsupported results contain no inferred institution/date/action/rate. Reasons
    describe the failed support conditions; they are not negative event evidence.
    """
    result: dict[str, Any] = {
        "method": _METHOD, "supported": False, "institution": None,
        "event_date": None, "action": None, "rate_percent": None,
        "evidence": [], "source_content_hash": article.content_hash,
        "human_verified": False, "reasons": [],
    }
    title = re.split(r"\.{3,}|…|\?", article.title, maxsplit=1)[0]
    actions = list(re.finditer(r"동결|인상|인하", title))
    if ("금리" not in title or len(actions) != 1 or _PROJECTION.search(title)
            or _RETAIL.search(title) or _OTHER_INSTITUTION.search(title)
            or _has_other_named_bank(title)
            or _HISTORICAL_PREFIX.search(title) or _OTHER_TIME.search(title)
            or len(re.findall(rf"{_NUMBER}\s*%", title)) > 1
            or re.search(r"→|->|⇒|⟶", title)):
        result["reasons"].append("unsupported_primary_headline")
        return result
    title_action = actions[0].group()

    try:
        published = datetime.fromisoformat((article.published_at or "").replace("Z", "+00:00"))
        if published.utcoffset() is None:
            raise ValueError("timezone required")
        local_date = published.astimezone(_KST).date()
    except (ValueError, TypeError, OverflowError):
        result["reasons"].append("missing_timezone_aware_publication")
        return result
    if _conflicting_calendar_date(title, local_date):
        result["reasons"].append("unsupported_primary_headline_date")
        return result
    dates = list(_TODAY.finditer(article.body[:700]))
    if not dates:
        result["reasons"].append("missing_explicit_today_date")
        return result
    if any(int(match["day"]) != local_date.day or
           (match["month"] is not None and int(match["month"]) != local_date.month)
           for match in dates):
        result["reasons"].append("ambiguous_or_mismatched_today_date")
        return result

    decisions = []
    explanations = []
    confirmations = []
    for start, end, sentence in _sentences(article.body):
        # Never treat a 1200-character truncation as a completed sentence.
        if end > 1200:
            break
        if (sentence.lstrip().startswith("▲") or _has_other_named_bank(sentence)
                or _OTHER_INSTITUTION.search(sentence) or _RETAIL.search(sentence)):
            continue
        confirmation = _CONFIRMATION.fullmatch(sentence)
        if confirmation:
            confirmations.append({
                "action": confirmation["action"], "assertion_span": (start, end),
                "policy_span": (start + confirmation.start("policy"), start + confirmation.end("policy")),
                "institution_span": (start + confirmation.start("institution"), start + confirmation.end("institution")),
                "same_day_span": (start + confirmation.start("same_day"), start + confirmation.end("same_day")),
            })
        sentence_dates = [date for date in _TODAY.finditer(sentence) if start + date.end() <= 700]
        if not sentence_dates:
            continue
        for match in _POLICY_ACTION.finditer(sentence):
            decision_dates = [date for date in sentence_dates if date.end() <= match.start()]
            if not decision_dates:
                continue
            prefix = sentence[:match.start()]
            suffix = sentence[match.end():]
            if (_HISTORICAL_PREFIX.search(prefix) or _OTHER_TIME.search(prefix)
                    or _conflicting_calendar_date(prefix, local_date)):
                continue
            # Both sides are full matches: an arbitrary quoted claim, reporting
            # source, new subject, or trailing conjecture never inherits support.
            direct_actor = _DIRECT_PREFIX.fullmatch(prefix)
            explanation_actor = _EXPLANATION_PREFIX.fullmatch(prefix)
            direct = bool(direct_actor and _DIRECT_END.fullmatch(suffix))
            causal = _CAUSAL_EXPLANATION_END.fullmatch(suffix) if explanation_actor else None
            # The month list belongs only to this explicitly different causal
            # background action. No arbitrary historical text is accepted or
            # re-dated by a later "이날" committee clause.
            scoped_history = bool(causal and causal["background_action"] != match["action"]
                                  and (causal["effect_action"] is None or causal["effect_action"] == causal["background_action"])
                                  and all(1 <= int(month) <= 12 for month in re.split(r"\s*[·,]\s*", causal["months"])))
            explanation = bool(explanation_actor and (_EXPLANATION_END.fullmatch(suffix) or scoped_history))
            if not direct and not explanation:
                continue
            actor = direct_actor if direct else explanation_actor
            decision = {
                "action": match["action"], "assertion_span": (start, end),
                "policy_span": (start + match.start(), start + match.end()),
                "institution_span": (start + actor.start("institution"), start + actor.end("institution")),
                "date_spans": [(start + date.start(), start + date.end()) for date in decision_dates],
                "confirmations": [],
            }
            (decisions if direct else explanations).append(decision)
    for explanation in explanations:
        followups = []
        for confirmation in confirmations:
            begin, end = explanation["assertion_span"][1], confirmation["assertion_span"][0]
            if end <= begin:
                continue
            between = article.body[begin:end]
            # "이날" may resolve to the explanation's today only if no intervening
            # historical or conflicting date creates a different antecedent.
            if (_HISTORICAL_PREFIX.search(between) or _OTHER_TIME.search(between)
                    or _conflicting_calendar_date(between, local_date)):
                continue
            followups.append(confirmation)
        if followups and {confirmation["action"] for confirmation in followups} == {explanation["action"]}:
            explanation["confirmations"] = followups
            decisions.append(explanation)
    if not decisions:
        result["reasons"].append("missing_completed_bok_decision")
        return result
    if {decision["action"] for decision in decisions} != {title_action}:
        result["reasons"].append("ambiguous_or_inconsistent_decision")
        return result

    evidence = [_evidence("title", article.title, 0, len(title))]
    targets: dict[str, list[dict[str, Any]]] = {}
    # Only the explicit policy phrase can supply its target. Narrative reasons
    # and quotations in an explanation cannot donate an unrelated old level.
    rate_spans = [decision["policy_span"] for decision in decisions]
    rate_spans.extend(confirmation["policy_span"] for decision in decisions for confirmation in decision["confirmations"])
    for field, raw, begin, end in [("title", article.title, 0, len(title))] + [
        ("body", article.body, begin, end) for begin, end in rate_spans
    ]:
        for target in _TARGET.finditer(raw[begin:end]):
            targets.setdefault(_canonical_rate(target["rate"]), []).append(
                _evidence(field, raw, begin + target.start(), begin + target.end()))
    if len(targets) > 1:
        result["reasons"].append("ambiguous_target_rate")
        return result
    for decision in decisions:
        for field in ("assertion_span", "policy_span", "institution_span"):
            evidence.append(_evidence("body", article.body, *decision[field]))
        for date_span in decision["date_spans"]:
            evidence.append(_evidence("body", article.body, *date_span))
        for confirmation in decision["confirmations"]:
            for field in ("assertion_span", "policy_span", "institution_span", "same_day_span"):
                evidence.append(_evidence("body", article.body, *confirmation[field]))
    for spans in targets.values():
        evidence.extend(spans)
    # Preserve evidence order but remove identical spans from repeated decisions.
    unique = {(span["field"], span["start"], span["end"]): span for span in evidence}
    result.update(supported=True, institution="bank_of_korea", event_date=local_date.isoformat(),
                  action=_ACTION[title_action], rate_percent=next(iter(targets), None),
                  evidence=list(unique.values()))
    return result


def compare_bok_decision_anchors(left: dict, right: dict) -> dict[str, Any]:
    """Compare supported anchors; absence never constitutes a conflict."""
    conflicts = []
    for field in ("institution", "event_date", "action", "rate_percent"):
        a, b = left.get(field), right.get(field)
        if a is not None and b is not None:
            if field == "rate_percent":
                a, b = _canonical_rate(str(a)), _canonical_rate(str(b))
            if a != b:
                conflicts.append(field)
    known = all(anchor.get("supported") is True and anchor.get("method") == _METHOD
                and anchor.get("institution") == "bank_of_korea"
                and anchor.get("event_date") and anchor.get("action") in _ACTION.values()
                for anchor in (left, right))
    return {"method": _METHOD, "compatible": bool(known and not conflicts),
            "conflicts": conflicts, "human_verified": False}
