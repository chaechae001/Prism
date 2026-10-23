from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from news_clustering.core.embedding_cache import CachedNewsE5Encoder


class LocalTestEncoder(CachedNewsE5Encoder):
    """Deterministic batch-independent vectors; no ONNX/network dependency in unit tests."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []

    def _encode_missing(self, texts):
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            values = np.tile(np.frombuffer(sha256(text.encode()).digest(), dtype=np.uint8), 12).astype(np.float32) + 1
            vectors.append(values / np.linalg.norm(values))
        self.last_diagnostics = {'backend': 'unit_test', 'article_count': len(texts)}
        return np.asarray(vectors)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model = self.root / 'model'
        (self.model / 'onnx').mkdir(parents=True)
        (self.model / 'tokenizer.json').write_bytes(b'local-test-tokenizer')
        (self.model / 'onnx/model_quantized.onnx').write_bytes(b'local-test-model')
        self.cache = self.root / 'cache.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def encoder(self, **kwargs):
        return LocalTestEncoder(self.cache, model_dir=self.model, **kwargs)

    def test_second_process_instance_reuses_vectors_in_reordered_input(self):
        first = self.encoder()
        expected = first.encode(['제목A\n본문A', '제목B\n본문B'])
        second = self.encoder()
        actual = second.encode(['제목B\n본문B', '제목A\n본문A'])
        np.testing.assert_array_equal(actual, expected[[1, 0]])
        self.assertEqual(second.calls, [])
        self.assertEqual(second.last_diagnostics['cache']['hit_count'], 2)

    def test_changed_body_recomputes_only_that_article(self):
        encoder = self.encoder()
        encoder.encode(['제목A\n본문A', '제목B\n본문B'])
        encoder.encode(['제목A\n수정된 본문A', '제목B\n본문B'])
        self.assertEqual(encoder.calls[-1], ['제목A\n수정된 본문A'])
        self.assertEqual(encoder.last_diagnostics['cache']['hit_count'], 1)
        self.assertEqual(encoder.last_diagnostics['cache']['miss_count'], 1)

    def test_duplicate_text_is_encoded_once_without_changing_output_order(self):
        encoder = self.encoder()
        values = encoder.encode(['a', 'b', 'a'])
        self.assertEqual(encoder.calls, [['a', 'b']])
        np.testing.assert_array_equal(values[0], values[2])
        self.assertEqual(encoder.last_diagnostics['cache']['unique_text_count'], 2)

    def test_model_bytes_and_representation_settings_separate_cache_namespaces(self):
        self.encoder().encode(['a'])
        changed_config = self.encoder(title_weight=0.7)
        changed_config.encode(['a'])
        self.assertEqual(changed_config.calls, [['a']])
        (self.model / 'onnx/model_quantized.onnx').write_bytes(b'another-model')
        changed_model = self.encoder()
        changed_model.encode(['a'])
        self.assertEqual(changed_model.calls, [['a']])

    def test_mutating_representation_settings_is_rejected_before_a_stale_hit(self):
        for name, value in [('title_weight', .9), ('window_tokens', 256), ('overlap_tokens', 32), ('batch_size', 4)]:
            encoder = self.encoder()
            encoder.encode(['a'])
            setattr(encoder, name, value)
            with self.assertRaisesRegex(ValueError, 'settings changed'):
                encoder.encode(['a'])

    def test_exact_float_settings_and_tokenizer_bytes_invalidate_cache(self):
        self.encoder(title_weight=.6).encode(['a'])
        nearby = self.encoder(title_weight=.60000001)
        nearby.encode(['a'])
        self.assertEqual(nearby.calls, [['a']])
        (self.model / 'tokenizer.json').write_bytes(b'a-new-tokenizer')
        changed_tokenizer = self.encoder()
        changed_tokenizer.encode(['a'])
        self.assertEqual(changed_tokenizer.calls, [['a']])

    def test_corrupted_cached_vector_is_recomputed(self):
        expected = self.encoder().encode(['a'])
        with closing(sqlite3.connect(self.cache)) as connection:
            with connection:
                connection.execute('UPDATE embeddings SET vector = ?', (b'corrupt',))
        repaired = self.encoder()
        np.testing.assert_array_equal(repaired.encode(['a']), expected)
        self.assertEqual(repaired.calls, [['a']])
        self.assertEqual(repaired.last_diagnostics['cache']['corrupt_entry_count'], 1)

    def test_bad_fresh_vectors_do_not_poison_cache(self):
        class BadEncoder(LocalTestEncoder):
            def _encode_missing(self, texts):
                return np.full((len(texts), 384), np.nan, dtype=np.float32)
        with self.assertRaises(ValueError):
            BadEncoder(self.cache, model_dir=self.model).encode(['a'])
        valid = self.encoder()
        valid.encode(['a'])
        self.assertEqual(valid.calls, [['a']])

    def test_missing_local_model_fails_without_downloading_or_creating_cache(self):
        (self.model / 'tokenizer.json').unlink()
        with self.assertRaises(FileNotFoundError):
            self.encoder()
        self.assertFalse(self.cache.exists())

    def test_empty_input_does_not_create_cache_and_has_fixed_dimensions(self):
        encoder = self.encoder()
        self.assertEqual(encoder.encode([]).shape, (0, 384))
        self.assertFalse(self.cache.exists())
        self.assertEqual(encoder.calls, [])


if __name__ == '__main__':
    unittest.main()
