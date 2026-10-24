"""Local encoders. Models are downloaded as data, never executed as remote Python."""

from hashlib import sha256
import json
from pathlib import Path
from typing import Protocol

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


E5_REPO = "Xenova/multilingual-e5-small"
E5_REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"


class TextEncoder(Protocol):
    model_id: str
    last_diagnostics: dict

    def encode(self, texts: list[str]) -> np.ndarray: ...


def lexical_vectors(texts: list[str]) -> np.ndarray:
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4),
                                 sublinear_tf=True, max_features=40_000, dtype=np.float32)
    try:
        return vectorizer.fit_transform(texts).toarray()
    except ValueError as exc:
        if "empty vocabulary" not in str(exc):
            raise
        return TfidfVectorizer(analyzer="char", ngram_range=(1, 1), dtype=np.float32).fit_transform(texts).toarray()


class TfidfEncoder:
    model_id = "char-tfidf-2-4/v1"

    def __init__(self):
        self.last_diagnostics = {"backend": "tfidf", "semantic_model": False}

    def encode(self, texts: list[str]) -> np.ndarray:
        return lexical_vectors(texts)


class RecordingEncoder:
    def __init__(self, encoder: TextEncoder):
        self.encoder = encoder
        self.model_id = encoder.model_id
        self.vectors = None
        self.text_hashes = []

    @property
    def last_diagnostics(self):
        return self.encoder.last_diagnostics

    def encode(self, texts: list[str]) -> np.ndarray:
        self.text_hashes = [sha256(text.encode('utf-8')).hexdigest() for text in texts]
        self.vectors = np.asarray(self.encoder.encode(texts), dtype=np.float32)
        return self.vectors

    def save(self, path: Path) -> None:
        np.savez_compressed(path,
                            vectors=self.vectors if self.vectors is not None else np.empty((0, 0), dtype=np.float32),
                            text_hashes=np.asarray(self.text_hashes, dtype=str),
                            model_id=np.asarray(self.model_id),
                            diagnostics=np.asarray(json.dumps(self.last_diagnostics, ensure_ascii=False)))


class VectorFileEncoder:
    def __init__(self, path: Path):
        with np.load(path, allow_pickle=False) as cache:
            self.vectors = cache['vectors'].copy()
            self.text_hashes = cache['text_hashes'].tolist()
            self.model_id = str(cache['model_id'].item())
            self.last_diagnostics = json.loads(str(cache['diagnostics'].item()))

    def encode(self, texts: list[str]) -> np.ndarray:
        hashes = [sha256(text.encode('utf-8')).hexdigest() for text in texts]
        if hashes != self.text_hashes:
            raise ValueError('Vector cache does not match article content/order; regenerate embeddings')
        return self.vectors.copy()


def mean_pool(hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    mask = np.asarray(attention_mask, dtype=np.float32)[..., None]
    pooled = (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
    norm = np.linalg.norm(pooled, axis=1, keepdims=True)
    return (pooled / np.maximum(norm, 1e-12)).astype(np.float32)


class E5Encoder:
    model_id = f"{E5_REPO}@{E5_REVISION}:onnx-int8"

    def __init__(self, model_dir: str | Path = ".models/multilingual-e5-small", batch_size: int = 8):
        self.model_dir = Path(model_dir)
        self.batch_size = batch_size
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.last_diagnostics = {}

    def encode(self, texts: list[str]) -> np.ndarray:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        paths = {}
        for filename in ("tokenizer.json", "onnx/model_quantized.onnx"):
            path = self.model_dir / filename
            if not path.exists():
                from huggingface_hub import hf_hub_download
                path = Path(hf_hub_download(repo_id=E5_REPO, filename=filename,
                                           revision=E5_REVISION, local_dir=str(self.model_dir)))
            paths[filename] = path
        tokenizer = Tokenizer.from_file(str(paths["tokenizer.json"]))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        prefixed = ["query: " + text for text in texts]
        lengths = [len(encoded.ids) for encoded in tokenizer.encode_batch(prefixed)]
        tokenizer.enable_truncation(max_length=512)
        pad_token = "<pad>" if tokenizer.token_to_id("<pad>") is not None else "[PAD]"
        pad_id = tokenizer.token_to_id(pad_token)
        if pad_id is None:
            raise ValueError("Model tokenizer has no supported padding token")
        tokenizer.enable_padding(pad_id=pad_id, pad_token=pad_token)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(paths["onnx/model_quantized.onnx"]),
                                       sess_options=options, providers=["CPUExecutionProvider"])
        input_names = {item.name for item in session.get_inputs()}
        batches = []
        for start in range(0, len(texts), self.batch_size):
            encoded = tokenizer.encode_batch(prefixed[start:start + self.batch_size])
            inputs = {
                "input_ids": np.asarray([x.ids for x in encoded], dtype=np.int64),
                "attention_mask": np.asarray([x.attention_mask for x in encoded], dtype=np.int64),
                "token_type_ids": np.asarray([x.type_ids for x in encoded], dtype=np.int64),
            }
            hidden = session.run(None, {key: value for key, value in inputs.items() if key in input_names})[0]
            batches.append(mean_pool(hidden, inputs["attention_mask"]))
        self.last_diagnostics = {
            "backend": "onnx_cpu_int8", "base_model": "intfloat/multilingual-e5-small",
            "model_repo": E5_REPO, "model_revision": E5_REVISION, "dimensions": 384,
            "prefix": "query: ", "max_tokens": 512, "pooling": "masked_mean_l2",
            "truncated_article_count": sum(length > 512 for length in lengths),
            "input_token_counts": lengths,
        }
        return np.concatenate(batches) if batches else np.empty((0, 384), dtype=np.float32)


class NewsE5Encoder(E5Encoder):
    """Separate headline and token-window body views; retain original input hashes."""

    def __init__(self, model_dir: str | Path = '.models/multilingual-e5-small', batch_size: int = 8,
                 *, title_weight: float = 0.6, window_tokens: int = 384, overlap_tokens: int = 64):
        import math
        from news_clustering.core.news_views import token_windows

        super().__init__(model_dir, batch_size)
        if not math.isfinite(title_weight) or not 0 <= title_weight <= 1:
            raise ValueError('title_weight must be between zero and one')
        token_windows([], size=window_tokens, overlap=overlap_tokens)
        if window_tokens > 448:
            raise ValueError('Body windows must leave space below the 512-token E5 limit')
        self.title_weight = title_weight
        self.window_tokens = window_tokens
        self.overlap_tokens = overlap_tokens
        self.model_id = (f'{E5Encoder.model_id}:news-title-body-v2:'
                         f'w{title_weight:g}:tokens{window_tokens}:overlap{overlap_tokens}')

    def encode(self, texts: list[str]) -> np.ndarray:
        from tokenizers import Tokenizer
        from news_clustering.core.news_views import aggregate_views, token_windows

        if not texts:
            return np.empty((0, 384), dtype=np.float32)
        path = self.model_dir / 'tokenizer.json'
        if not path.exists():
            from huggingface_hub import hf_hub_download
            path = Path(hf_hub_download(repo_id=E5_REPO, filename='tokenizer.json',
                                       revision=E5_REVISION, local_dir=str(self.model_dir)))
        tokenizer = Tokenizer.from_file(str(path))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        views, mappings, original_counts, body_token_counts = [], [], [], []
        for text in texts:
            title, separator, body = text.partition('\n')
            mapping = {'title': len(views), 'body': [], 'weights': []}
            views.append(title)
            body_ids = tokenizer.encode(body, add_special_tokens=False).ids if separator and body.strip() else []
            body_token_counts.append(len(body_ids))
            original_counts.append(len(tokenizer.encode('query: ' + text).ids))
            for ids, weight in token_windows(body_ids, size=self.window_tokens, overlap=self.overlap_tokens):
                mapping['body'].append(len(views))
                mapping['weights'].append(weight)
                views.append(tokenizer.decode(ids, skip_special_tokens=True))
            mappings.append(mapping)
        vectors = super().encode(views)
        base = dict(self.last_diagnostics)
        lengths = base.get('input_token_counts', [])
        self.last_diagnostics = {
            **base, 'representation': 'title_body_token_windows_v2',
            'title_weight': self.title_weight, 'body_weight': 1 - self.title_weight,
            'window_tokens': self.window_tokens, 'overlap_tokens': self.overlap_tokens,
            'article_count': len(texts), 'view_count': len(views),
            'body_window_count': sum(len(m['body']) for m in mappings),
            'long_article_count': sum(n > 512 for n in original_counts),
            'truncated_article_count': sum(any(lengths[i] > 512 for i in [m['title'], *m['body']]) for m in mappings),
            'input_token_counts': original_counts, 'view_token_counts': lengths,
            'body_token_count': sum(body_token_counts),
            'body_tokens_covered': sum(sum(m['weights']) for m in mappings),
        }
        return aggregate_views(vectors, mappings, title_weight=self.title_weight)
