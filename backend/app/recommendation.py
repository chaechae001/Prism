"""A deterministic mock policy, not evidence of reducing filter bubbles."""
import base64
import json
from collections import Counter
from .models import FeedItem, Reason, Story

LABELS = {'latest':'최근에 업데이트된 사건', 'public_interest':'함께 살펴볼 주요 이슈',
          'source_diversity':'여러 출처를 비교할 수 있어요', 'discovery':'주제의 폭을 넓히는 발견'}

def rank(stories: list[Story], mode: str, diversity: int):
    latest = sorted(stories, key=lambda s: (-s.updated_at.timestamp(), s.id))
    if mode == 'latest':
        return [FeedItem(story=s,reason=Reason(code='latest', label=LABELS['latest'])) for s in latest], False
    categories, publishers, leads = Counter(), Counter(), Counter()
    pool = list(latest)
    result = []
    relaxed = False
    fresh = {s.id: 1 - i / max(1,len(latest)) for i,s in enumerate(latest)}
    weight = diversity / 100
    def score(s):
        sources = {a.publisher_id for a in s.articles}
        overlap = sum(publishers[p] for p in sources) / len(sources)
        bonus = .25 if mode == 'explore' and categories[s.category] == 0 else 0
        return .65*s.public_interest + .35*fresh[s.id] - weight*(.3*categories[s.category]+.1*overlap) + weight*bonus
    while pool:
        candidates = [s for s in pool if leads[s.articles[0].publisher_id] < 2] if diversity >= 50 else pool
        if not candidates:
            candidates = pool
            relaxed = True
        best = sorted(candidates, key=lambda s: (-score(s), s.id))[0]
        code = 'discovery' if result and categories[best.category] == 0 and diversity >= 50 else 'source_diversity' if diversity >= 50 else 'public_interest'
        result.append(FeedItem(story=best,reason=Reason(code=code,label=LABELS[code])))
        categories[best.category]+=1
        for p in {a.publisher_id for a in best.articles}: publishers[p]+=1
        leads[best.articles[0].publisher_id]+=1
        pool.remove(best)
    return result, relaxed

def cursor_key(version, q, category, mode, diversity):
    return [version, q, category or '', mode, diversity]

def encode_cursor(key, offset):
    return base64.urlsafe_b64encode(json.dumps([*key,offset],ensure_ascii=False,separators=(',',':')).encode()).decode().rstrip('=')

def decode_cursor(cursor, key, total):
    try:
        value=json.loads(base64.b64decode(cursor + '='*(-len(cursor)%4), altchars=b'-_', validate=True))
        if not isinstance(value,list) or len(value)!=6 or value[:5]!=key or type(value[5]) is not int or not 0 < value[5] <= total:
            raise ValueError()
        return value[5]
    except Exception:
        raise ValueError('Cursor does not match this query or dataset') from None
