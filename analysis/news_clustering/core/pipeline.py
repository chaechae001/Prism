"""Deterministic candidate grouping. No RSS, filesystem or database calls."""

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from itertools import combinations
import math
import re

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from news_clustering.core.embeddings import TextEncoder, TfidfEncoder, lexical_vectors
from news_clustering.core.verification import VerificationConfig, select_candidates, verify_candidates, verification_score
from news_clustering.models import Article


@dataclass(frozen=True)
class ClusterConfig:
    k_candidates: tuple[int, ...] = (8, 12, 16, 20, 24, 32)
    min_similarity: float = 0.89
    min_lexical_similarity: float = 0.08
    min_title_similarity: float = 0.0
    rescue_margin: float = 0.02
    max_event_gap_hours: float = 48.0
    random_state: int = 42
    max_articles: int = 2000
    use_kmeans: bool = True

    def __post_init__(self):
        if type(self.use_kmeans) is not bool:
            raise ValueError('use_kmeans must be a boolean')
        for value in (self.min_similarity, self.min_lexical_similarity, self.min_title_similarity, self.rescue_margin):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Similarity settings must be finite numbers between 0 and 1")
        if not math.isfinite(self.max_event_gap_hours) or self.max_event_gap_hours <= 0:
            raise ValueError("max_event_gap_hours must be positive and finite")
        if self.max_articles < 1 or any(not isinstance(k, int) or k < 1 for k in self.k_candidates):
            raise ValueError("max_articles and K candidates must be positive integers")


def _timestamps(articles):
    times = []
    for article in articles:
        try:
            date = datetime.fromisoformat((article.published_at or "").replace("Z", "+00:00"))
            times.append(date.timestamp() if date.tzinfo is not None else None)
        except (ValueError, TypeError, OverflowError):
            times.append(None)
    return times


def _choose_k(vectors, config):
    count = len(vectors)
    distinct = len(np.unique(np.round(vectors, decimals=7), axis=0))
    if count < 3 or distinct < 2:
        return np.zeros(count, dtype=int), (None if count < 2 else 1), []
    candidates = sorted({k for k in config.k_candidates if 2 <= k <= min(count - 1, distinct)})
    if not candidates:
        candidates = [2]
    comparisons, best = [], None
    for k in candidates:
        model = KMeans(n_clusters=k, n_init=10, random_state=config.random_state)
        labels = model.fit_predict(vectors)
        if not 2 <= len(set(labels)) < count:
            continue
        score = float(silhouette_score(vectors, labels, metric="cosine",
                                        sample_size=min(count, 1000), random_state=config.random_state))
        comparisons.append({"k": k, "silhouette_cosine": round(score, 6), "inertia": round(float(model.inertia_), 6)})
        if best is None or score > best[0]:
            best = (score, k, labels)
    if best is None:
        return np.zeros(count, dtype=int), 1, comparisons
    return best[2], best[1], comparisons


def _surface_terms(article):
    # Display hints only: these are surface words, not verified named entities.
    stop = {'오늘', '올해', '지난', '대한', '관련', '기자', '있다', '했다', '한다',
            '있는', '통해', '위해', '이번', '이날', '따르면', '밝혔다', '밝혔습니다'}
    terms = set(re.findall(r'[가-힣]{2,}|[A-Za-z][A-Za-z0-9-]+', article.title + ' ' + article.body[:600]))
    result = set()
    for term in terms:
        for suffix in ('에서는', '으로는', '에서', '으로', '에게', '에는', '은', '는', '이', '가', '을', '를', '의', '와', '과'):
            if term.endswith(suffix) and len(term) - len(suffix) >= 2:
                term = term[:-len(suffix)]
                break
        if term not in stop:
            result.add(term)
    return result


def cluster_articles(articles: list[Article | dict], config: ClusterConfig | None = None,
                     *, encoder: TextEncoder | None = None, pair_scorer=None,
                     verification: VerificationConfig | None = None) -> dict:
    config = config or ClusterConfig()
    if verification is not None and pair_scorer is None:
        raise ValueError('Verification requires an explicit pair scorer; fallback is not automatic')
    if pair_scorer is not None:
        verification = verification or VerificationConfig()
    normalized = [a if isinstance(a, Article) else Article.from_dict(a) for a in articles]
    normalized.sort(key=lambda a: a.article_id)
    count = len(normalized)
    if len({a.article_id for a in normalized}) != count:
        raise ValueError("Duplicate article_id values; deduplicate inputs before clustering")
    if count > config.max_articles:
        raise ValueError(f"This experiment supports at most {config.max_articles} articles per run")
    encoder = encoder or TfidfEncoder()
    algorithm = 'kmeans-title-evidence/v2' if config.min_title_similarity > 0 else 'kmeans-complete-link-candidates/v1'
    if not config.use_kmeans:
        algorithm = 'complete-link-title-evidence/v2' if config.min_title_similarity > 0 else 'complete-link-candidates/v1'
    if verification is not None:
        supervised=getattr(pair_scorer,'scorer_kind',None)=='supervised_event_classifier'
        algorithm = ('kmeans-' if config.use_kmeans else '') + ('supervised-event-pair/v1' if supervised else 'cross-encoder-candidates/v3')
    result = {"schema_version": "1.0", "algorithm_version": algorithm,
              "model_id": encoder.model_id, "config": asdict(config), "groups": [],
              "diagnostics": {"article_count": count, "selected_k": None, "k_comparison": [],
                              "accuracy_measured": False, "requires_human_review": True,
                              "review_pairs": [], "coarse_assignments": {}}}
    if verification is not None:
        result['pair_verification'] = {'model_id': pair_scorer.model_id, 'config': asdict(verification)}
        if supervised:result['pair_verification']['scorer_kind']='supervised_event_classifier'
    if not normalized:
        if verification is not None:
            verify_candidates([], [], pair_scorer, verification)
            result['diagnostics']['verification_pairs'] = []
            result['diagnostics']['verification'] = {'candidate_pair_count': 0, 'possible_pair_count': 0,
                'unscored_pair_count': 0, 'event_rules_enabled': verification.event_rules,
                'scorer': dict(pair_scorer.last_diagnostics), 'accuracy_measured': False}
        return result
    vectors = np.asarray(encoder.encode([a.text for a in normalized]), dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != count or vectors.shape[1] == 0 or not np.isfinite(vectors).all():
        raise ValueError("Encoder must return a finite nonempty N x D matrix in input order")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms < 1e-12):
        raise ValueError("Encoder returned a zero vector")
    vectors = vectors / norms
    semantic = np.clip(vectors @ vectors.T, -1, 1)
    lexical = lexical_vectors([f"{a.title} {a.title} {a.body[:600]}" for a in normalized])
    lexical = np.clip(lexical @ lexical.T, 0, 1)
    title_vectors = lexical_vectors([a.title for a in normalized])
    title_similarity = np.clip(title_vectors @ title_vectors.T, 0, 1)
    surface_terms = [_surface_terms(a) for a in normalized]
    term_frequency = Counter(term for terms in surface_terms for term in terms)
    if config.use_kmeans:
        labels, selected_k, comparisons = _choose_k(vectors, config)
    else:
        labels, selected_k, comparisons = np.zeros(count, dtype=int), None, []
    times = _timestamps(normalized)
    eligible = np.zeros((count, count), dtype=bool)
    pair_data, pair_evidence = [], {}
    for left, right in combinations(range(count), 2):
        known_time = times[left] is not None and times[right] is not None
        in_time = known_time and abs(times[left] - times[right]) <= config.max_event_gap_hours * 3600
        strong_title = config.min_title_similarity > 0 and title_similarity[left, right] >= 0.25
        boundary_penalty = config.rescue_margin if labels[left] != labels[right] and not strong_title else 0
        required = min(1.0, config.min_similarity + boundary_penalty)
        title_ok = title_similarity[left, right] >= config.min_title_similarity
        allowed = in_time and semantic[left, right] >= required and lexical[left, right] >= config.min_lexical_similarity and title_ok
        eligible[left, right] = eligible[right, left] = allowed
        pair_data.append((left, right, float(semantic[left, right]), float(lexical[left, right]), bool(in_time)))
        reasons = []
        if not known_time:
            reasons.append('missing_publication_date')
        elif not in_time:
            reasons.append('publication_time_gap')
        if semantic[left, right] < required:
            reasons.append('below_semantic_threshold')
        if lexical[left, right] < config.min_lexical_similarity:
            reasons.append('weak_text_evidence')
        if not title_ok:
            reasons.append('weak_title_evidence')
        pair_evidence[left, right] = {
            'title_similarity': round(float(title_similarity[left, right]), 6),
            'required_similarity': round(float(required), 6), 'eligible': bool(allowed),
            'strong_title_boundary_rescue': bool(strong_title and labels[left] != labels[right]),
            'reasons': reasons or ['candidate_rule_match'],
        }

    verified = {}
    if verification is not None:
        candidates = select_candidates(normalized, semantic, times, eligible, verification,
                                       max_gap_hours=config.max_event_gap_hours)
        verified = verify_candidates(normalized, candidates, pair_scorer, verification)
        for (left, right), evidence in pair_evidence.items():
            evidence['baseline_eligible'], evidence['baseline_reasons'] = evidence['eligible'], evidence['reasons']
            value = verified.get((left, right))
            if (value is not None and value['eligible'] and verification.require_baseline_evidence
                    and not evidence['baseline_eligible']):
                value.update(eligible=False, decision='review', requires_human_review=True,
                             reasons=['baseline_evidence_not_satisfied'])
            evidence.update(value or {'eligible': False, 'decision': 'not_retrieved',
                                      'requires_human_review': False, 'reasons': ['not_retrieved_for_verification']})
            eligible[left, right] = eligible[right, left] = evidence['eligible']
        result['diagnostics']['verification'] = {
            'candidate_pair_count': len(candidates), 'possible_pair_count': count * (count - 1) // 2,
            'unscored_pair_count': count * (count - 1) // 2 - len(candidates),
            'candidate_selection': 'time_window_top_k_union_and_baseline_eligible_pairs',
            'event_rules_enabled': verification.event_rules,
            'baseline_evidence_required': verification.require_baseline_evidence,
            'scorer': dict(pair_scorer.last_diagnostics),
            'accuracy_measured': False,
        }

    # Greedy complete-link checks: every cross pair must pass, avoiding A-B-C chains.
    owners = list(range(count))
    buckets = {i: [i] for i in range(count)}
    def edge_order(pair):
        left, right, sim, lex, _ = pair
        score = verification_score(verified[left, right]) if verification is not None else sim
        return (-score, -sim, -lex, normalized[left].article_id, normalized[right].article_id)
    edges = sorted((pair for pair in pair_data if eligible[pair[0], pair[1]]), key=edge_order)
    for left, right, *_ in edges:
        first, second = owners[left], owners[right]
        if first == second:
            continue
        if not eligible[np.ix_(buckets[first], buckets[second])].all():
            continue
        for member in buckets[second]:
            owners[member] = first
        buckets[first] = sorted(buckets[first] + buckets.pop(second))

    groups = []
    for indices in buckets.values():
        ids = [normalized[i].article_id for i in indices]
        submatrix = semantic[np.ix_(indices, indices)]
        representative = indices[int(submatrix.mean(axis=1).argmax())]
        off_diagonal = submatrix[np.triu_indices(len(indices), 1)]
        publishers = sorted({normalized[i].publisher for i in indices if normalized[i].publisher})
        categories = Counter(normalized[i].category for i in indices)
        shared = set.intersection(*(surface_terms[i] for i in indices)) if len(indices) > 1 else set()
        shared = sorted(shared, key=lambda term: (term_frequency[term], -len(term), term))[:8]
        title_pairs = title_similarity[np.ix_(indices, indices)][np.triu_indices(len(indices), 1)]
        groups.append({
            "group_id": "group-" + sha256("|".join(ids).encode()).hexdigest()[:16],
            "article_ids": ids, "representative_article_id": normalized[representative].article_id,
            "representative_title": normalized[representative].title,
            "article_count": len(ids), "publishers": publishers, "publisher_count": len(publishers),
            "category": sorted(categories, key=lambda key: (-categories[key], key))[0],
            "status": "candidate" if len(ids) > 1 else "singleton", "same_event_confirmed": False,
            "min_pair_similarity": round(float(off_diagonal.min()), 6) if len(off_diagonal) else None,
            "mean_pair_similarity": round(float(off_diagonal.mean()), 6) if len(off_diagonal) else None,
            "kmeans_labels": sorted({int(labels[i]) for i in indices}) if config.use_kmeans else [],
            "evidence": {'shared_terms': shared, 'term_method': 'surface_words_not_ner',
                         'min_title_similarity': round(float(title_pairs.min()), 6) if len(title_pairs) else None,
                         'title_guard_enabled': config.min_title_similarity > 0,
                         'body_kinds': dict(Counter(normalized[i].body_kind for i in indices))},
        })
        if verification is not None:
            scores = [verification_score(verified[left, right]) for left, right in combinations(indices, 2)]
            groups[-1]['evidence']['min_classifier_score' if supervised else 'min_reranker_score'] = min(scores) if scores else None
            groups[-1]['evidence']['classifier_score_is_event_probability' if supervised else 'reranker_score_is_event_probability'] = False
    groups.sort(key=lambda group: (-group["article_count"], -group["publisher_count"], group["group_id"]))
    result["groups"] = groups
    def describe_pair(pair):
        left, right, sim, lex, in_time = pair
        evidence = dict(pair_evidence[left, right])
        together = owners[left] == owners[right]
        if evidence['eligible'] and not together:
            evidence['reasons'] = ['complete_link_conflict']
        return {'article_ids': [normalized[left].article_id, normalized[right].article_id],
                'similarity': round(sim, 6), 'lexical_similarity': round(lex, 6),
                'within_time_window': in_time, 'grouped_together': together, **evidence}
    ordered_pairs = sorted(pair_data, key=lambda pair: (-pair[2], pair[0], pair[1]))
    review = [describe_pair(pair) for pair in ordered_pairs
              if pair[4] and pair[2] >= config.min_similarity - 0.04 and owners[pair[0]] != owners[pair[1]]]
    review_limit = 60
    if verification is not None:
        result['diagnostics']['verification_pairs'] = [describe_pair(pair) for pair in ordered_pairs
                                                       if (pair[0], pair[1]) in verified]
        review = [describe_pair(pair) for pair in ordered_pairs
                  if pair_evidence[pair[0], pair[1]].get('requires_human_review')]
        review_limit = verification.max_pairs
    result["diagnostics"].update({
        "selected_k": selected_k, "k_comparison": comparisons,
        "coarse_assignments": {a.article_id: int(labels[i]) for i, a in enumerate(normalized)} if config.use_kmeans else {},
        "group_count": len(groups), "multi_article_group_count": sum(g["article_count"] > 1 for g in groups),
        "multi_publisher_group_count": sum(g["publisher_count"] > 1 for g in groups),
        "singleton_count": sum(g["article_count"] == 1 for g in groups),
        "missing_publication_date_count": sum(t is None for t in times),
        "body_kinds": dict(Counter(a.body_kind for a in normalized)),
        "embedding": getattr(encoder, "last_diagnostics", {}),
        "top_pairs": [describe_pair(pair) for pair in ordered_pairs[:30]],
        "review_pairs": review[:review_limit], "review_pair_total": len(review), "review_pair_limit": review_limit,
    })
    return result
