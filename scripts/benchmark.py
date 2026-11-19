"""Command-line benchmark (same code as Administration -> Validation; see app/services/benchmark.py).

  docker run --rm -v "$PWD/models:/models:ro" -v "$PWD/backend:/app" -v /path/to/sets:/datasets:ro -w /app \
      safeface/worker:dev python /app/../scripts/benchmark.py --module image.aigen.npr --dataset /datasets/team-set

Prints the results as JSON; runs started from the web UI are stored in the database instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "/app")

from app.services.benchmark import auc, ece, f1_iou, run_benchmark, tpr_at  # noqa: E402,F401  (re-exported for tests)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", required=True)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--robustness", action="store_true")
    args = ap.parse_args()
    record = run_benchmark(args.module, args.dataset, args.robustness)
    record["run_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
