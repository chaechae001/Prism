"""Validate analyst input without printing source content or connecting by default."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.worker import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="분석 기사 입력 사전 검증")
    parser.add_argument("input", type=Path, nargs="?", default=ROOT / "contracts/analyst-batch.example.json")
    parser.add_argument("--check-db", action="store_true")
    args = parser.parse_args()
    raise SystemExit(main(["validate-batch", "--input", str(args.input), *(["--check-db"] if args.check_db else [])]))
