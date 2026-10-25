"""Opt-in full/lead consensus around indivisible core-v2 seed groups.

No LLM or labels. New connections require two semantic views, lexical evidence,
known nearby publication times, mutual neighbours, and complete-link agreement.
An inherited v2 connection is retained even when this extra view disagrees.
"""

from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from hashlib import sha256
from itertools import combinations
import math

import numpy as np

from news_clustering.core.analysis_text import prepare_article
from news_clustering.core.decision_anchors import extract_bok_decision_anchor, compare_bok_decision_anchors
from news_clustering.core.embeddings import RecordingEncoder, lexical_vectors
from news_clustering.core.event_evidence import compare_event_evidence
from news_clustering.core.pipeline import ClusterConfig, cluster_articles
from news_clustering.core.shared_summaries import audit_shared_summaries
from news_clustering.models import Article


_ANCHOR_LIMITS = {'full_similarity_min': .90, 'lead_similarity_min': .90,
                  'title_lexical_min': .025, 'lead_lexical_min': .08,
                  'strict_cross_pair_required': True,
                  'scope': 'source-explicit-current-day-BOK-primary-rate-decision'}


@dataclass(frozen=True)
class MultiViewConfig:
    full_similarity_floor: float = .90
    lead_similarity_min: float = .96
    title_lexical_min: float = .10
    lead_lexical_min: float = .15
    max_gap_hours: float = 24.
    mutual_top_k: int = 3
    lead_characters: int = 600
    max_articles: int = 500
    detail_limit: int = 200

    def __post_init__(self):
        for name in ('full_similarity_floor', 'lead_similarity_min', 'title_lexical_min', 'lead_lexical_min'):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError('View thresholds must be finite positive numbers at most one')
        if type(self.max_gap_hours) not in (int, float) or not math.isfinite(self.max_gap_hours) or self.max_gap_hours <= 0:
            raise ValueError('max_gap_hours must be finite and positive')
        for name in ('mutual_top_k', 'lead_characters', 'max_articles', 'detail_limit'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError('View limits must be positive integers')


def multiview_settings(profile):
    if profile == 'multiview':
        return MultiViewConfig()
    if profile in {'multiview-dev', 'multiview-group', 'multiview-anchor'}:
        # Exploratory development calibration, explicitly not held-out tuning.
        return MultiViewConfig(full_similarity_floor=.93, lead_similarity_min=.935,
                               title_lexical_min=.08, lead_lexical_min=.25)
    raise ValueError('Unknown multiview profile')


def lead_view(article, characters=600):
    if type(characters) is not int or characters < 1:
        raise ValueError('Lead character budget must be a positive integer')
    prepared = prepare_article(article)
    text = prepared.article.body[:characters]
    return replace(prepared.article, body=text), {
        'article_id': article.article_id, 'source_content_hash': article.content_hash,
        'analysis_only': True, 'analysis_body_start': 0, 'analysis_body_end': len(text),
        'text': text, 'cleanup': prepared.audit,
        'note': 'Exact prefix of the cleaned analysis body; not extracted event facts or a summary.'}


def _matrix(vectors, count):
    values = np.asarray(vectors, dtype=np.float32)
    if (values.ndim != 2 or values.shape[0] != count or values.shape[1] == 0
            or not np.isfinite(values).all() or np.any(np.linalg.norm(values, axis=1) < 1e-12)):
        raise ValueError('Expected finite nonzero vectors in article-ID order')
    values = values / np.linalg.norm(values, axis=1, keepdims=True)
    return np.clip(values @ values.T, -1, 1)


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def _seed_neighbour_gate(seeds, allowed, lead, top_k, *, strict_allowed=None):
    """Rank feasible seed pairs by their weakest cross-pair lead similarity.

    Eligibility is checked before ranking; rejected pairs cannot consume slots.
    Seeds stay fixed here. Later merges still require every cross pair to pass.
    """
    identities = sorted(seeds)
    choices = {identity: [] for identity in identities}
    feasible, missing_bridge = set(), set()
    for left, right in combinations(identities, 2):
        cross = np.ix_(seeds[left], seeds[right])
        if not allowed[cross].all():
            continue
        if strict_allowed is not None and not strict_allowed[cross].any():
            missing_bridge.add((left, right))
            continue
        score = float(lead[cross].min())
        feasible.add((left, right))
        choices[left].append((right, score))
        choices[right].append((left, score))
    choices = {identity: sorted(values, key=lambda value: (-value[1], value[0]))[:top_k]
               for identity, values in choices.items()}
    neighbours = {identity: {other for other, _ in values} for identity, values in choices.items()}
    mutual = {(left, right) for left, right in feasible
              if right in neighbours[left] and left in neighbours[right]}
    rejected = {}
    for left, right in combinations(identities, 2):
        if (left, right) in mutual:
            continue
        allowed[np.ix_(seeds[left], seeds[right])] = False
        allowed[np.ix_(seeds[right], seeds[left])] = False
        rejected[left, right] = ('not_mutual_seed_neighbours' if (left, right) in feasible else
                                 'seed_group_no_strict_bridge' if (left, right) in missing_bridge else
                                 'seed_group_cross_pair_failed')
    return rejected, {
        'neighbor_scope': 'seed_group',
        'seed_rank_criterion': 'minimum_cross_pair_lead_cosine_then_seed_id',
        'seed_group_count': len(identities),
        'possible_seed_group_pair_count': len(identities) * (len(identities) - 1) // 2,
        'feasible_seed_group_pair_count': len(feasible),
        'mutual_seed_group_pair_count': len(mutual),
        'seed_neighbours': [{'group_id': identity, 'article_count': len(seeds[identity]),
                             'neighbours': [{'group_id': other, 'minimum_lead_similarity': round(score, 6)}
                                            for other, score in choices[identity]]}
                            for identity in identities],
    }


def _format_groups(articles, buckets, semantic, coarse, baseline_owner):
    groups = []
    for members in buckets.values():
        ids = [articles[index].article_id for index in members]
        matrix = semantic[np.ix_(members, members)]
        representative = members[int(matrix.mean(axis=1).argmax())]
        scores = matrix[np.triu_indices(len(members), 1)]
        publishers = sorted({articles[index].publisher for index in members if articles[index].publisher})
        categories = Counter(articles[index].category for index in members)
        groups.append({
            'group_id': 'group-' + sha256('|'.join(ids).encode()).hexdigest()[:16],
            'article_ids': ids, 'representative_article_id': articles[representative].article_id,
            'representative_title': articles[representative].title, 'article_count': len(ids),
            'publishers': publishers, 'publisher_count': len(publishers),
            'category': sorted(categories, key=lambda key: (-categories[key], key))[0],
            'status': 'candidate' if len(ids) > 1 else 'singleton', 'same_event_confirmed': False,
            'min_pair_similarity': round(float(scores.min()), 6) if len(scores) else None,
            'mean_pair_similarity': round(float(scores.mean()), 6) if len(scores) else None,
            'kmeans_labels': sorted({coarse[identity] for identity in ids}) if coarse else [],
            'evidence': {'method': 'full-and-lead-consensus/v1',
                         'source_v2_group_ids': sorted({baseline_owner[index] for index in members}),
                         'inherited_relations_are_not_human_verified': True},
        })
    return sorted(groups, key=lambda group: (-group['article_count'], -group['publisher_count'], group['group_id']))


def cluster_multiview(articles, config=None, *, encoder, lead_encoder, settings=None, neighbor_scope='article',
                      anchor_rescue=False):
    if not isinstance(neighbor_scope, str) or neighbor_scope not in {'article', 'seed_group'}:
        raise ValueError('Expected article or seed_group neighbour scope')
    if type(anchor_rescue) is not bool or (anchor_rescue and neighbor_scope != 'seed_group'):
        raise ValueError('Source-anchor rescue requires a boolean and seed_group scope')
    settings = MultiViewConfig() if settings is None else settings
    config = config or ClusterConfig(min_similarity=.94, min_title_similarity=.025)
    if not isinstance(settings, MultiViewConfig):
        raise ValueError('Expected MultiViewConfig settings')
    items = sorted([item if isinstance(item, Article) else Article.from_dict(item) for item in articles],
                   key=lambda article: article.article_id)
    if len(items) > settings.max_articles:
        raise ValueError('Multiview article limit exceeded')
    full_recorded = RecordingEncoder(encoder)
    baseline = cluster_articles(items, config, encoder=full_recorded)
    common = {'schema_version': '1.0', 'algorithm_version': 'v2-seeded-full-and-lead-consensus/v1',
              'model_id': encoder.model_id, 'config': baseline['config'],
              'multiview_config': asdict(settings), 'baseline_result': baseline}
    seed_audit = {}
    source_anchors, shared_audit, flagged_ids = {}, {}, set()
    if anchor_rescue:
        source_anchors = {article.article_id: extract_bok_decision_anchor(article) for article in items}
        shared_audit = audit_shared_summaries(items)
        flagged_ids = set(shared_audit['article_ids_requiring_review'])
        common['algorithm_version'] = 'v2-seeded-source-anchor-strict-bridge/v1'
        common['multiview_config']['anchor_rescue'] = dict(_ANCHOR_LIMITS)
    if neighbor_scope == 'seed_group':
        if not anchor_rescue:
            common['algorithm_version'] = 'v2-seeded-full-and-lead-group-neighbours/v1'
        common['multiview_config']['neighbor_scope'] = 'seed_group'
    if not items:
        if neighbor_scope == 'seed_group':
            _, seed_audit = _seed_neighbour_gate({}, np.empty((0, 0), dtype=bool),
                                                  np.empty((0, 0)), settings.mutual_top_k)
        if anchor_rescue:
            seed_audit.update(shared_summary_audit=shared_audit, anchor_rescue={
                'method': 'bok-source-anchor-strict-bridge/v1', 'config': dict(_ANCHOR_LIMITS),
                'anchors': {}, 'relaxed_pair_candidate_count': 0, 'grouped_relaxed_pair_count': 0,
                'rule_developed_on_inspected_sources': True, 'human_verified': False})
        return {**common, 'groups': [], 'diagnostics': {**baseline['diagnostics'], 'multiview': {
            'added_pair_count': 0, 'removed_pair_count': 0, 'baseline_view_disagreement_count': 0,
            'full_text_hashes': [], 'lead_text_hashes': [], 'lead_views': [], 'review_pairs': [], **seed_audit}}}
    semantic = _matrix(full_recorded.vectors, len(items))
    views_and_audits = [lead_view(article, settings.lead_characters) for article in items]
    views = [pair[0] for pair in views_and_audits]
    lead_recorded = RecordingEncoder(lead_encoder)
    lead = _matrix(lead_recorded.encode([article.text for article in views]), len(items))
    title_values = lexical_vectors([article.title for article in views])
    lexical_values = lexical_vectors([article.text for article in views])
    title_similarity = np.clip(title_values @ title_values.T, 0, 1)
    lexical_similarity = np.clip(lexical_values @ lexical_values.T, 0, 1)
    index = {article.article_id: position for position, article in enumerate(items)}
    baseline_owner, buckets = {}, {}
    for group in baseline['groups']:
        members = [index[identity] for identity in group['article_ids']]
        buckets[members[0]] = members
        baseline_owner.update({position: group['group_id'] for position in members})
    owners = {position: first for first, members in buckets.items() for position in members}
    times = [_time(article.published_at) for article in items]
    max_gap = min(settings.max_gap_hours, config.max_event_gap_hours) * 3600
    within = np.zeros((len(items), len(items)), dtype=bool)
    for left, right in combinations(range(len(items)), 2):
        within[left, right] = within[right, left] = (times[left] is not None and times[right] is not None
            and abs(times[left] - times[right]) <= max_gap)
    nearest = []
    for left in range(len(items)):
        candidates = [right for right in range(len(items))
                      if baseline_owner[left] != baseline_owner[right] and within[left, right]]
        nearest.append(set(sorted(candidates, key=lambda right: (-float(lead[left, right]), items[right].article_id))[:settings.mutual_top_k]))
    allowed = np.zeros_like(within)
    strict_allowed = np.zeros_like(within) if anchor_rescue else None
    relaxed_pairs = set()
    edges, details, inherited_disagreements = [], [], 0
    for left, right in combinations(range(len(items)), 2):
        inherited = baseline_owner[left] == baseline_owner[right]
        reasons = []
        for failed, reason in (
            (not within[left, right], 'missing_or_distant_publication_time'),
            (semantic[left, right] < settings.full_similarity_floor, 'weak_full_view'),
            (lead[left, right] < settings.lead_similarity_min, 'weak_lead_view'),
            (title_similarity[left, right] < settings.title_lexical_min, 'weak_headline_evidence'),
            (lexical_similarity[left, right] < settings.lead_lexical_min, 'weak_lead_lexical_evidence'),
        ):
            if failed:
                reasons.append(reason)
        mutual = right in nearest[left] and left in nearest[right]
        if neighbor_scope == 'article' and not inherited and not mutual:
            reasons.append('not_mutual_neighbours')
        anchor_match = compare_bok_decision_anchors(source_anchors[items[left].article_id],
                                                    source_anchors[items[right].article_id]) if anchor_rescue else None
        inspect = inherited or (semantic[left, right] >= settings.full_similarity_floor
                                and lead[left, right] >= settings.lead_similarity_min - .02 and within[left, right])
        if anchor_rescue:
            inspect = inspect or (anchor_match['compatible'] and within[left, right])
        if inspect:
            event = compare_event_evidence(items[left], items[right])
            reasons.extend(event['conflicts'])
        else:
            event = None
        if anchor_rescue:
            reasons.extend('source_anchor_' + conflict + '_conflict' for conflict in anchor_match['conflicts'])
        eligible = not reasons
        strict_reasons = list(reasons)
        relaxed = False
        if anchor_rescue:
            strict_allowed[left, right] = strict_allowed[right, left] = eligible
            relaxed = (not inherited and not eligible and anchor_match['compatible']
                and not anchor_match['conflicts'] and within[left, right]
                and not (event and event['conflicts'])
                and not ({items[left].article_id, items[right].article_id} & flagged_ids)
                and semantic[left, right] >= _ANCHOR_LIMITS['full_similarity_min']
                and lead[left, right] >= _ANCHOR_LIMITS['lead_similarity_min']
                and title_similarity[left, right] >= _ANCHOR_LIMITS['title_lexical_min']
                and lexical_similarity[left, right] >= _ANCHOR_LIMITS['lead_lexical_min'])
            if relaxed:
                relaxed_pairs.add((left, right))
                eligible, reasons = True, []
        allowed[left, right] = allowed[right, left] = inherited or eligible
        if eligible and not inherited:
            edges.append((left, right))
        if inherited and reasons:
            inherited_disagreements += 1
        if inspect:
            details.append({'article_ids': [items[left].article_id, items[right].article_id],
                            'inherited_v2_relation': inherited, 'eligible_new_connection': eligible and not inherited,
                            'full_similarity': round(float(semantic[left, right]), 6),
                            'lead_similarity': round(float(lead[left, right]), 6),
                            'title_similarity': round(float(title_similarity[left, right]), 6),
                            'lead_lexical_similarity': round(float(lexical_similarity[left, right]), 6),
                            'reasons': reasons, 'headline_clues': event})
            if anchor_rescue:
                details[-1].update(
                    connection_route='inherited_v2' if inherited else 'source_anchor' if relaxed else 'strict' if eligible else 'blocked',
                    strict_rejection_reasons=strict_reasons, source_anchor_match=anchor_match)
    if neighbor_scope == 'seed_group':
        seeds = {baseline_owner[members[0]]: members for members in buckets.values()}
        rejected, seed_audit = _seed_neighbour_gate(seeds, allowed, lead, settings.mutual_top_k,
                                                   strict_allowed=strict_allowed)
        edges = [(left, right) for left, right in edges if allowed[left, right]]
        for detail in details:
            if detail['inherited_v2_relation']:
                continue
            first, second = (index[identity] for identity in detail['article_ids'])
            reason = rejected.get(tuple(sorted((baseline_owner[first], baseline_owner[second]))))
            if reason:
                detail['reasons'].append(reason)
                detail['eligible_new_connection'] = False
    for left, right in sorted(edges, key=lambda pair: (-float(lead[pair]), -float(semantic[pair]), pair)):
        first, second = owners[left], owners[right]
        if first == second or not allowed[np.ix_(buckets[first], buckets[second])].all():
            continue
        for member in buckets[second]:
            owners[member] = first
        buckets[first] = sorted(buckets[first] + buckets.pop(second))
    added = []
    for left, right in combinations(range(len(items)), 2):
        if owners[left] == owners[right] and baseline_owner[left] != baseline_owner[right]:
            added.append([items[left].article_id, items[right].article_id])
    for detail in details:
        left, right = (index[identity] for identity in detail['article_ids'])
        detail['grouped_together'] = owners[left] == owners[right]
    details.sort(key=lambda pair: (not (pair['grouped_together'] and not pair['inherited_v2_relation']),
                                  not pair['inherited_v2_relation'], -pair['lead_similarity'], pair['article_ids']))
    groups = _format_groups(items, buckets, semantic, baseline['diagnostics']['coarse_assignments'], baseline_owner)
    if neighbor_scope == 'seed_group':
        for group in groups:
            group['evidence']['method'] = 'full-and-lead-group-neighbours/v1'
    if anchor_rescue:
        grouped_relaxed = [(left, right) for left, right in sorted(relaxed_pairs) if owners[left] == owners[right]]
        for group in groups:
            group['evidence']['method'] = 'source-anchor-strict-bridge/v1'
            group['quality_review_required'] = bool(set(group['article_ids']) & flagged_ids)
            group['quality_review_reasons'] = ['identical_cleaned_body_different_headlines'] if group['quality_review_required'] else []
        seed_audit.update(shared_summary_audit=shared_audit, anchor_rescue={
            'method': 'bok-source-anchor-strict-bridge/v1', 'config': dict(_ANCHOR_LIMITS),
            'anchors': source_anchors, 'relaxed_pair_candidate_count': len(relaxed_pairs),
            'grouped_relaxed_pair_count': len(grouped_relaxed),
            'grouped_relaxed_pairs': [[items[left].article_id, items[right].article_id] for left, right in grouped_relaxed],
            'rule_developed_on_inspected_sources': True, 'human_verified': False})
    diagnostics = {key: baseline['diagnostics'].get(key) for key in ('article_count', 'selected_k', 'k_comparison',
                   'coarse_assignments', 'embedding', 'body_kinds', 'missing_publication_date_count')}
    diagnostics.update(accuracy_measured=False, requires_human_review=True, group_count=len(groups),
                       multi_article_group_count=sum(group['article_count'] > 1 for group in groups),
                       singleton_count=sum(group['article_count'] == 1 for group in groups))
    diagnostics['multiview'] = {
        'baseline_groups_preserved': True, 'added_pair_count': len(added), 'removed_pair_count': 0,
        'added_pairs': added[:settings.detail_limit], 'pair_detail_limit': settings.detail_limit,
        'baseline_view_disagreement_count': inherited_disagreements,
        'review_pair_count': len(details), 'review_pairs': details[:settings.detail_limit],
        'full_text_hashes': full_recorded.text_hashes, 'lead_text_hashes': lead_recorded.text_hashes,
        'lead_model_id': lead_encoder.model_id, 'lead_embedding': lead_recorded.last_diagnostics,
        'lead_views': [pair[1] for pair in views_and_audits], 'new_connections_are_human_verified': False,
        **seed_audit,
    }
    return {**common, 'groups': groups, 'diagnostics': diagnostics}
