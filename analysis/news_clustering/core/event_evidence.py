"""Conservative, inspectable headline clues. This is not an NER/event model."""

from datetime import date
import re

from news_clustering.models import Article


RULE_VERSION = 'headline-event-clues/v1'
# A small pilot vocabulary: absence is unknown, never evidence of a different actor.
ENTITY_ALIASES = {
    'CATL': ('CATL', '닝더스다이'), '화웨이': ('화웨이', 'Huawei'),
    '한국은행': ('한국은행', '한은'), '대한상공회의소': ('대한상공회의소', '대한상의'),
    '한국소비자원': ('한국소비자원', '소비자원'), '국회': ('국회',),
    '금융감독원': ('금융감독원', '금감원'), '공정거래위원회': ('공정거래위원회', '공정위'),
    'LH': ('LH', '한국토지주택공사'), '네이버': ('네이버', 'NAVER'),
}
TARGET_PATTERNS = {
    'battery_swap': r'배터리\s*(?:교환|교체)|스와핑|battery\s*swap',
    'energy_storage': r'\bESS\b|에너지\s*저장',
    'currency_market': r'환율|원.?달러|달러.?원',
    'equity_market': r'코스피|코스닥',
    'corporate_profitability': r'수익성|영업이익률|기업경영분석',
    'corporate_exports': r'중견기업.{0,15}수출|수출.{0,15}중견기업',
}
EXCLUSIVE_TARGETS = {
    frozenset(('battery_swap', 'energy_storage')),
    frozenset(('currency_market', 'corporate_profitability')),
    frozenset(('currency_market', 'corporate_exports')),
    frozenset(('corporate_profitability', 'corporate_exports')),
}
ACTION_PATTERNS = {
    'agreement': r'협약|MOU|계약|협력|체결',
    'launch': r'출시|공개|개관|오픈',
    'expansion': r'확대|늘린|인상',
    'report': r'보고서|조사|통계|분석|발표',
    'market_update': r'급등|급락|반등|하락|마감|장중|연저점',
}


def _contains_alias(text, alias):
    if alias.isascii():
        return bool(re.search(r'(?<![A-Za-z0-9])' + re.escape(alias) + r'(?![A-Za-z0-9])', text, re.I))
    return alias in text


def headline_facts(article: Article) -> dict:
    title = article.title
    # Dates are taken only from the headline, never photo captions or publication time.
    dates = set()
    for match in re.finditer(r'(?:(\d{4})년\s*)?(\d{1,2})월\s*(\d{1,2})일', title):
        y, m, d = match.groups()
        try:
            checked = date(int(y) if y else 2000, int(m), int(d))
            dates.add(checked.isoformat() if y else '--' + checked.strftime('%m-%d'))
        except ValueError:
            pass
    return {
        'entities': sorted(key for key, aliases in ENTITY_ALIASES.items()
                           if any(_contains_alias(title, alias) for alias in aliases)),
        'targets': sorted(key for key, pattern in TARGET_PATTERNS.items() if re.search(pattern, title, re.I)),
        'actions': sorted(key for key, pattern in ACTION_PATTERNS.items() if re.search(pattern, title, re.I)),
        'explicit_headline_dates': sorted(dates),
    }


def compare_event_evidence(first: Article, second: Article) -> dict:
    left, right = headline_facts(first), headline_facts(second)
    shared_entities = sorted(set(left['entities']) & set(right['entities']))
    shared_targets = sorted(set(left['targets']) & set(right['targets']))
    shared_actions = sorted(set(left['actions']) & set(right['actions']))
    conflicts = []
    # Mixed-topic headlines stay uncertain; a side mention cannot veto a whole pair.
    if len(left['targets']) == len(right['targets']) == 1:
        if frozenset((left['targets'][0], right['targets'][0])) in EXCLUSIVE_TARGETS:
            conflicts.append('event_target_conflict')
    if ('equity_market' in shared_targets and left['explicit_headline_dates']
            and right['explicit_headline_dates']
            and not any(a == b or ((a.startswith('--') or b.startswith('--')) and a[-5:] == b[-5:])
                        for a in left['explicit_headline_dates'] for b in right['explicit_headline_dates'])):
        conflicts.append('event_date_conflict')
    supported = bool(shared_targets or (shared_entities and shared_actions))
    return {'method': RULE_VERSION, 'scope': 'limited_headline_rules_not_ner',
            'status': 'conflict' if conflicts else 'limited_match' if supported else 'unknown',
            'left': left, 'right': right, 'shared_entities': shared_entities,
            'shared_targets': shared_targets, 'shared_actions': shared_actions, 'conflicts': conflicts,
            'missing_information_is_negative_evidence': False}
