"""Run explicitly to enrich a saved local run with image URLs, never image files."""
import argparse
import json
import sys
from .collection import collect_images, validate_destination, write_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description='Collect RSS/Open Graph image URLs for a saved clustering run')
    parser.add_argument('--results-dir', required=True)
    parser.add_argument('--output', required=True, help='Fresh JSON path outside the original clustering output')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args(argv)
    try:
        validate_destination(args.output, args.results_dir)
        result = collect_images(args.results_dir, limit=args.limit, progress=lambda value: print(value, flush=True))
        write_manifest(result, args.output, args.results_dir)
        print(json.dumps(result['summary'], ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        print('Image metadata collection failed; check the saved input and use a fresh output path.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
