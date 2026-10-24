"""Reuse the identity-checked collector; extract photo metadata on the same request."""
from dataclasses import dataclass,field
from datetime import datetime,timedelta,timezone

from ..article_images.metadata import image_from_html
from rss_fulltext_crawler.rss_crawler.selection import SelectionPolicy


@dataclass(frozen=True)
class _PrioritySelection(SelectionPolicy):
    observations: dict = field(default_factory=dict)
    selected: dict = field(default_factory=dict)

    def plan(self,source,body,limit):
        from rss_fulltext_crawler.rss_crawler.parsing import parse_feed
        eligible={}
        for item in parse_feed(body,source):
            if SelectionPolicy.reason(self,item) is None:
                eligible.setdefault(item['article_id'],item)
        oldest=datetime.min.replace(tzinfo=timezone.utc)
        ordered=sorted(eligible.values(),key=lambda r:(r['article_id'] in self.observations,
            self.observations.get(r['article_id'],oldest),r['rss_position']))
        self.selected[source.key+'-'+source.category]={r['article_id'] for r in ordered[:limit]}

    def reason(self,item):
        reason=SelectionPolicy.reason(self,item)
        if reason is not None:return reason
        if item['article_id'] not in self.selected.get(item['source_id'],set()):
            return 'refetch_budget_deferred' if item['article_id'] in self.observations else 'eligible_over_limit'
        return None


class _MetadataClient:
    def __init__(self,client,*,selection=None,sources=None,limit=100):
        self.client=client
        self.images={}
        self.selection=selection;self.sources=sources or {};self.limit=limit

    @property
    def requests_made(self):return self.client.requests_made

    def get(self,url,max_bytes,identity=None):
        from rss_fulltext_crawler.rss_crawler.network import decode_html
        response=self.client.get(url,max_bytes,identity)
        if identity is not None:
            candidate=image_from_html(decode_html(response),response.url)
            if candidate:self.images[identity]=candidate
        elif self.selection is not None and url in self.sources:
            self.selection.plan(self.sources[url],response.body,self.limit)
        return response


def collect_rows(settings,*,known_ids,cutoff,client=None,observations=None):
    from rss_fulltext_crawler.rss_crawler.runner import collect
    from rss_fulltext_crawler.rss_crawler.network import CrawlClient
    from rss_fulltext_crawler.rss_crawler.parsing import SOURCES,article_identity
    active={s.key:s for s in settings.active_sources}
    if not active:return dict(articles=[],summary={'active_sources':0})
    selection=_PrioritySelection((cutoff-timedelta(hours=settings.window_hours)).isoformat(),
        cutoff.isoformat(),excluded_article_ids=frozenset(known_ids),observations=observations or {})
    proxy=_MetadataClient(client if client is not None else CrawlClient(),selection=selection,
        sources={SOURCES[key].feed_url:SOURCES[key] for key in active},limit=settings.limit_per_feed)
    result=collect([SOURCES[key] for key in active],limit=settings.limit_per_feed,
        min_chars=settings.min_body_characters,client=proxy,selection=selection)
    rows=[]
    for original in result['results']:
        if original['status']!='ok':continue
        identity=article_identity(original['url'])
        if identity is None or identity[0] not in active:raise ValueError('Collected article source mismatch')
        source=SOURCES[identity[0]]
        if original['source_id']!=source.key+'-'+source.category or original['publisher']!=source.publisher:
            raise ValueError('Collected publisher metadata mismatch')
        # The old collector's unknown placeholder is replaced only for this newly
        # requested article by its explicit source policy, never for saved inputs.
        candidate=proxy.images.get(identity)
        row={**original,'rights':dict(active[identity[0]].rights),'is_demo':False,
             'usage_scope':'local_test','publisher_permission_verified':False,
             'source_notice':'사용자 승인 로컬 테스트 수집 · 언론사 이용 허가 미확인',
             'image_url':candidate['url'] if candidate else None,
             'image_origin':candidate['origin'] if candidate else None}
        if row['rights']['display_image']=='denied':row.update(image_url=None,image_origin=None)
        rows.append(row)
    complete=(all(r['status']=='ok' and not r.get('excluded_by_reason',{}).get('eligible_over_limit',0)
                  for r in result['source_reports'])
              and result['summary']['selected_articles']==result['summary']['extracted_count'])
    summary={**result['summary'],'sources':[
        dict(key=r['source'],status=r['status'],selected=r['selected_items'],
             deferred=r.get('excluded_by_reason',{})) for r in result['source_reports']]}
    return dict(articles=rows,summary=summary,complete=complete)
