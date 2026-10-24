"""Token coverage and title/body aggregation independent of model and database."""

import math

import numpy as np


def token_windows(token_ids: list[int], *, size: int = 384, overlap: int = 64):
    if not isinstance(size, int) or not isinstance(overlap, int) or size < 1 or not 0 <= overlap < size:
        raise ValueError('Window size must be positive and overlap smaller than size')
    windows = []
    previous_end = 0
    for start in range(0, len(token_ids), size - overlap):
        end = min(start + size, len(token_ids))
        windows.append((token_ids[start:end], end - previous_end))
        previous_end = end
        if end == len(token_ids):
            break
    return windows


def aggregate_views(vectors: np.ndarray, mappings: list[dict], *, title_weight: float = 0.6) -> np.ndarray:
    if not math.isfinite(title_weight) or not 0 <= title_weight <= 1:
        raise ValueError('title_weight must be between zero and one')
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim != 2 or not np.isfinite(vectors).all():
        raise ValueError('View embeddings must be a finite matrix')
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms < 1e-12):
        raise ValueError('View embeddings cannot contain zero vectors')
    unit = vectors / norms
    result = []
    for mapping in mappings:
        title = unit[mapping['title']]
        if not mapping['body']:
            combined = title
        else:
            weights = np.asarray(mapping['weights'], dtype=np.float32)
            if len(weights) != len(mapping['body']) or not np.isfinite(weights).all() or np.any(weights <= 0):
                raise ValueError('Body windows need positive coverage weights')
            body = np.average(unit[mapping['body']], axis=0, weights=weights)
            body_norm = np.linalg.norm(body)
            if body_norm < 1e-12:
                raise ValueError('Body windows cancel to a zero vector')
            combined = title_weight * title + (1 - title_weight) * body / body_norm
        norm = np.linalg.norm(combined)
        if norm < 1e-12:
            raise ValueError('Combined article embedding is a zero vector')
        result.append(combined / norm)
    return np.asarray(result, dtype=np.float32).reshape(len(mappings), vectors.shape[1])
