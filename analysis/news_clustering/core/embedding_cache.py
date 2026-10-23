"""Per-text local E5 cache. No remote service, model download, or raw text storage.

This cache deliberately wraps NewsE5Encoder only: batch-fitted TF-IDF vectors
cannot be reused per article when the population changes.
"""

from contextlib import closing
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import sqlite3
from time import perf_counter

import numpy as np

from news_clustering.core.embeddings import NewsE5Encoder


def _file_hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b''):
            digest.update(chunk)
    return digest.hexdigest()


class CachedNewsE5Encoder(NewsE5Encoder):
    """Reuse unchanged inputs across batches; verify model bytes and vector blobs."""

    def __init__(self, cache_path: str | Path, model_dir: str | Path = '.models/multilingual-e5-small',
                 batch_size: int = 8, *, title_weight=0.6, window_tokens=384, overlap_tokens=64):
        super().__init__(model_dir, batch_size, title_weight=title_weight,
                         window_tokens=window_tokens, overlap_tokens=overlap_tokens)
        self.cache_path = Path(cache_path)
        self._fixed_settings = self._settings()
        self._model_files()  # Fail before creating a cache if local model data is missing.

    def _settings(self):
        return {'title_weight': self.title_weight, 'window_tokens': self.window_tokens,
                'overlap_tokens': self.overlap_tokens, 'batch_size': self.batch_size}

    def _model_files(self):
        paths = {name: self.model_dir / name for name in ('tokenizer.json', 'onnx/model_quantized.onnx')}
        for path in paths.values():
            if not path.is_file():
                raise FileNotFoundError(f'Local E5 model file is required; automatic download is disabled: {path}')
        return paths

    def _encode_missing(self, texts):
        return super().encode(texts)

    def encode(self, texts: list[str]) -> np.ndarray:
        if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
            raise TypeError('texts must be a list of strings')
        if self._settings() != self._fixed_settings:
            raise ValueError('Encoder settings changed; create a new CachedNewsE5Encoder with the new configuration')
        if not texts:
            self.last_diagnostics = {'backend': 'onnx_cpu_int8_cached', 'article_count': 0,
                                     'cache': {'hit_count': 0, 'miss_count': 0, 'unique_text_count': 0}}
            return np.empty((0, 384), dtype=np.float32)
        started = perf_counter()
        files = {name: _file_hash(path) for name, path in self._model_files().items()}
        runtimes = {}
        for package in ('onnxruntime', 'tokenizers', 'numpy'):
            try:
                runtimes[package] = version(package)
            except PackageNotFoundError:
                runtimes[package] = 'unavailable'
        identity = {'schema': 'news-e5-cache/1', 'model_id': self.model_id, 'model_files': files,
                    'representation': self._fixed_settings, 'runtime_versions': runtimes,
                    'dtype': 'float32-little-endian', 'dimensions': 384}
        namespace = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        hashes = [sha256(text.encode()).hexdigest() for text in texts]
        unique = dict(zip(hashes, texts))
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        cached, corrupt = {}, 0
        with closing(sqlite3.connect(self.cache_path, timeout=30)) as connection:
            with connection:
                connection.execute('''CREATE TABLE IF NOT EXISTS embeddings (
                    namespace TEXT NOT NULL, text_hash TEXT NOT NULL, dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL, vector_sha256 TEXT NOT NULL,
                    PRIMARY KEY (namespace, text_hash))''')
                for text_hash in unique:
                    row = connection.execute('SELECT dimensions, vector, vector_sha256 FROM embeddings '
                                             'WHERE namespace = ? AND text_hash = ?', (namespace, text_hash)).fetchone()
                    if row is None:
                        continue
                    dimension, blob, checksum = row
                    if dimension != 384 or not isinstance(blob, bytes) or len(blob) != 384 * 4 or sha256(blob).hexdigest() != checksum:
                        corrupt += 1
                        continue
                    vector = np.frombuffer(blob, dtype='<f4').copy()
                    if not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-12:
                        corrupt += 1
                        continue
                    cached[text_hash] = vector
                missing = [value for value in unique if value not in cached]
                hit_count = sum(value in cached for value in hashes)
                lookup_seconds = perf_counter() - started
                inference_started = perf_counter()
                miss_diagnostics = None
                if missing:
                    values = np.asarray(self._encode_missing([unique[value] for value in missing]), dtype=np.float32)
                    if (values.shape != (len(missing), 384) or not np.isfinite(values).all()
                            or np.any(np.linalg.norm(values, axis=1) < 1e-12)):
                        raise ValueError('E5 cache requires finite nonzero N x 384 embeddings')
                    miss_diagnostics = dict(self.last_diagnostics)
                    for text_hash, vector in zip(missing, values):
                        blob = vector.astype('<f4').tobytes()
                        connection.execute('INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?, ?)',
                                           (namespace, text_hash, 384, blob, sha256(blob).hexdigest()))
                        cached[text_hash] = vector.copy()
                inference_seconds = perf_counter() - inference_started
        self.last_diagnostics = {
            'backend': 'onnx_cpu_int8_cached', 'article_count': len(texts), 'dimensions': 384,
            'cache': {'schema': identity['schema'], 'namespace': namespace, 'model_files': files,
                      'representation': self._fixed_settings.copy(), 'runtime_versions': runtimes,
                      'hit_count': hit_count, 'miss_count': len(texts) - hit_count,
                      'unique_text_count': len(unique), 'unique_miss_count': len(missing),
                      'corrupt_entry_count': corrupt, 'lookup_and_model_hash_seconds': lookup_seconds,
                      'inference_seconds': inference_seconds, 'total_seconds': perf_counter() - started},
            # These statistics cover only cache misses, never the whole batch on a warm run.
            'miss_embedding': miss_diagnostics,
        }
        return np.stack([cached[value] for value in hashes]).astype(np.float32)
