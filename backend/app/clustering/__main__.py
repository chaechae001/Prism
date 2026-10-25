"""Explicit local CLI. Does not load .env, connect to a DB or call an LLM."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from .adapter import CACHE_PATH, MODEL_DIR, PROFILES, run_batch


def main(argv=None):
    parser = argparse.ArgumentParser(description='PRISM local clusters and representative articles')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--input-format', choices=('analyst', 'collector'), default='analyst')
    parser.add_argument('--profile', choices=PROFILES, default='v2')
    parser.add_argument('--model-dir', type=Path, default=MODEL_DIR)
    parser.add_argument('--cache', type=Path, default=CACHE_PATH)
    args = parser.parse_args(argv)
    try:
        source = args.input.resolve()
        target = args.output_dir.resolve()
        if source == args.cache.resolve() or source == target or target in source.parents:
            raise ValueError('Input aliases a mutable destination')
        data = source.read_bytes()
        raw = json.loads(data.decode('utf-8-sig'))
        result = run_batch(raw, args.output_dir, input_format=args.input_format, profile=args.profile,
            model_dir=args.model_dir, cache_path=args.cache,
            provenance={'input_path': str(source), 'input_sha256': sha256(data).hexdigest()})
        print(json.dumps({'status': result['status'], 'article_count': result['article_count'],
                          'representative_count': result['group_count'],
                          'skipped_count': result['skipped_count'], 'output': str(target)}, ensure_ascii=False))
        return 0
    except Exception:
        print('Local clustering failed; check input, declared rights, body hash, model and fresh output path.',
              file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
