"""Candidate selection and pair decisions, independent of model/runtime/database."""

from dataclasses import dataclass
from math import exp, isfinite

import numpy as np

from news_clustering.core.event_evidence import compare_event_evidence


@dataclass(frozen=True)
class VerificationConfig:
    top_k: int = 5
    min_similarity: float = 0.90
    max_pairs: int = 1000
    accept_score: float = 0.80
    review_score: float = 0.35
    max_direction_gap: float = 0.25
    event_rules: bool = True
    require_baseline_evidence: bool = True

    def __post_init__(self):
        if type(self.top_k) is not int or self.top_k < 1 or type(self.max_pairs) is not int or self.max_pairs < 1:
            raise ValueError('top_k and max_pairs must be positive integers')
        for value in (self.min_similarity, self.accept_score, self.review_score, self.max_direction_gap):
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Verification thresholds must be finite and between 0 and 1')
        if (self.review_score > self.accept_score or type(self.event_rules) is not bool
                or type(self.require_baseline_evidence) is not bool):
            raise ValueError('Invalid verification review settings')


def select_candidates(articles, semantic, times, baseline_eligible, config, *, max_gap_hours):
    count = len(articles)
    pairs = set()
    for left in range(count):
        choices = [right for right in range(count) if left != right
                   and times[left] is not None and times[right] is not None
                   and abs(times[left] - times[right]) <= max_gap_hours * 3600
                   and semantic[left, right] >= config.min_similarity]
        choices.sort(key=lambda right: (-semantic[left, right], articles[right].article_id))
        pairs.update(tuple(sorted((left, right))) for right in choices[:config.top_k])
    pairs.update((left, right) for left, right in zip(*np.where(np.triu(baseline_eligible, 1))))
    if len(pairs) > config.max_pairs:
        raise ValueError(f'{len(pairs)} candidate pairs exceed max_pairs={config.max_pairs}; adjust explicit settings')
    return sorted(pairs)


def _sigmoid(value):
    return 1 / (1 + exp(-value)) if value >= 0 else exp(value) / (1 + exp(value))


def verify_candidates(articles, pairs, scorer, config):
    supervised=getattr(scorer,'scorer_kind',None)=='supervised_event_classifier'
    prefix='classifier' if supervised else 'reranker'
    raw = scorer.score_pairs([(articles[left], articles[right]) for left, right in pairs])
    if len(raw) != len(pairs):
        raise ValueError('Pair scorer must return one result per candidate pair')
    results = {}
    for (left, right), values in zip(pairs, raw):
        forward, reverse = float(values['forward_logit']), float(values['reverse_logit'])
        if not isfinite(forward) or not isfinite(reverse):
            raise ValueError('Pair scorer logits must be finite')
        forward_score, reverse_score = _sigmoid(forward), _sigmoid(reverse)
        score, gap = min(forward_score, reverse_score), abs(forward_score - reverse_score)
        evidence = compare_event_evidence(articles[left], articles[right])
        reasons = []
        if score < config.accept_score:
            reasons.append(prefix+'_below_threshold')
        if gap > config.max_direction_gap:
            reasons.append('reranker_direction_disagreement')
        if config.event_rules:
            reasons.extend(evidence['conflicts'])
        allowed = not reasons
        needs_review = (allowed or (score > config.review_score if supervised else score >= config.review_score) or gap > config.max_direction_gap
                        or (bool(evidence['conflicts']) and (not supervised or config.event_rules)))
        results[left, right] = {
            'eligible': allowed,
            'decision': 'candidate_match' if allowed else 'review' if needs_review else 'reject',
            'requires_human_review': needs_review,
            'reasons': reasons or [prefix+'_candidate_match'],
            ('event_classifier' if supervised else 'cross_encoder'): {'model_id': scorer.model_id, 'forward_logit': forward, 'reverse_logit': reverse,
                              'forward_score': forward_score, 'reverse_score': reverse_score,
                              'score': score, 'direction_gap': gap, 'aggregation': 'min_of_bidirectional_sigmoid',
                              'same_event_probability': False},
            'event_evidence': evidence,
        }
        if supervised:
            details=results[left,right]['event_classifier']
            details.update(aggregation='single_symmetric_feature_logit',
                           features=values['features'],feature_contributions=values['feature_contributions'],
                           intercept=values['intercept'],scores_are_calibrated_probabilities=False)
    return results


def verification_score(pair):
    return pair['event_classifier' if 'event_classifier' in pair else 'cross_encoder']['score']
