"""Conservative, source-specific analysis views with exact removal provenance.

The supplied Article is immutable. These rules never replace stored publisher text
and unknown structures remain in the analysis view for review.
"""

from dataclasses import dataclass, replace
import re

from news_clustering.models import Article


VERSION = 'source-analysis-cleanup/v2'
_TITLE = re.compile(r'^\s*(?:\[(?:여담야담|주영진 뉴스브리핑)\]\s*)+')
_NOTICE = re.compile(
    r'^\s*\[[^\]\n]{1,40}\]\s*인터뷰를\s*인용\s*보도할\s*때는'
    r'.{0,350}?저작권은\s*SBS에\s*있습니다\.\s*', re.S)
_HEADER = re.compile(r'^\s*■\s*방송\s*:.{0,1000}?■\s*진행\s*:.{0,200}?■\s*대담\s*:[^-]{0,600}-{6,}\s*', re.S)
_DESCRIPTION_HEADER = re.compile(
    r"^\s*['\"]?SBS\s*<[^>\n]{1,60}>['\"]?\s*"
    r'(?:■\s*<[^>\n]{1,60}>\s*)?■\s*진행\s*:\s*[^■\n]{1,50}앵커\s*'
    r'(?=■|$)')
_VIDEO_FOOTER = re.compile(r'\s*※\s*자세한\s*내용은\s*동영상으로\s*확인하실\s*수\s*있습니다\.\s*$')
_PHOTO_CREDIT = re.compile(r'\s*\(사진\s*=\s*[^()\n]{1,100}\)\s*$')


@dataclass(frozen=True)
class PreparedArticle:
    original: Article
    article: Article
    audit: dict


def headline_focus(title: str) -> dict:
    """An auxiliary lexical view, never a replacement for semantic title input.

    Only one complete double-quoted passage of at least 12 characters and half
    the headline is used. Multiple, short, or unbalanced quotes retain all text.
    These are surface-text clues, not extracted/verified event facts.
    """
    fallback = {'text': title, 'start': 0, 'end': len(title), 'method': 'full_headline_fallback'}
    balanced = ((title.count('"') == 2 and not title.count('“') and not title.count('”'))
                or (title.count('“') == title.count('”') == 1 and not title.count('"')))
    if not balanced:
        return fallback
    matches = list(re.finditer(r'"([^"\n]+)"|“([^”\n]+)”', title))
    if len(matches) != 1:
        return fallback
    match = matches[0]
    group = 1 if match.group(1) is not None else 2
    text = match.group(group)
    if len(text) < 12 or len(text) * 2 < len(title):
        return fallback
    return {'text': text, 'start': match.start(group), 'end': match.end(group),
            'method': 'single_substantial_quote'}


def prepare_article(article: Article) -> PreparedArticle:
    """Return an optional analysis view; all removed spans index the raw fields."""
    if not isinstance(article, Article):
        raise TypeError('prepare_article expects an Article')
    removed, warnings = [], []
    values = {'title': article.title, 'body': article.body}
    is_sbs = article.source_id == 'sbs' or article.source_id.startswith('sbs-')
    if is_sbs:
        title_match = _TITLE.match(article.title)
        if title_match and article.title[title_match.end():].strip():
            removed.append({'field': 'title', 'start': 0, 'end': title_match.end(),
                            'reason': 'broadcast_series_label', 'text': title_match.group()})
            values['title'] = article.title[title_match.end():]
        body = article.body
        start, end = 0, len(body)
        while True:
            previous_bounds = (start, end)
            for rule, pattern in [('broadcast_citation_notice', _NOTICE),
                                  ('broadcast_program_header', _HEADER), ('program_and_host_metadata', _DESCRIPTION_HEADER)]:
                match = pattern.match(body[start:end])
                if match:
                    stop = start + match.end()
                    removed.append({'field': 'body', 'start': start, 'end': stop,
                                    'reason': rule, 'text': body[start:stop]})
                    start = stop
            for rule, pattern in [('video_navigation_footer', _VIDEO_FOOTER), ('photo_credit', _PHOTO_CREDIT)]:
                match = pattern.search(body[start:end])
                if match:
                    begin = start + match.start()
                    removed.append({'field': 'body', 'start': begin, 'end': end,
                                    'reason': rule, 'text': body[begin:end]})
                    end = begin
            if (start, end) == previous_bounds:
                break
        values['body'] = body[start:end]
        if values['body'].lstrip().startswith('▲'):
            warnings.append('unparsed_leading_caption_marker')
        if values['body'].lstrip().startswith('■'):
            warnings.append('unparsed_broadcast_tail')
        if body.strip() and not values['body'].strip():
            warnings.append('title_only_after_cleanup')
    prepared = replace(article, **values)
    return PreparedArticle(article, prepared, {
        'version': VERSION, 'article_id': article.article_id, 'analysis_only': True,
        'original_content_hash': article.content_hash, 'analysis_content_hash': prepared.content_hash,
        'changed': prepared != article, 'removed_spans': removed, 'warnings': warnings,
        'original_body_characters': len(article.body), 'analysis_body_characters': len(prepared.body),
    })
