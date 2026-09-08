"""Run the independent SW2021 industry-stage pipeline manually."""

import argparse
import json

from industry_stage.pipeline import run_pipeline


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-classification", action="store_true")
    parser.add_argument("--backfill-days", type=int, default=10)
    args = parser.parse_args()
    result = run_pipeline(
        refresh_classification=args.refresh_classification,
        backfill_days=args.backfill_days,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
