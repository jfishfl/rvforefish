#!/usr/bin/env python3
"""Validate and summarize a foretravel-rvc soak TSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

# Make the packaged tool runnable directly from its `tools/` directory without
# requiring an undocumented PYTHONPATH.  The release layout always places the
# application package in the sibling `src/` directory.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from foretravel_rvc.soak import analyze_soak


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tsv")
    parser.add_argument("--min-samples", type=int, default=288)
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()

    with open(args.tsv, newline="", encoding="utf-8") as source:
        report = analyze_soak(
            csv.DictReader(source, delimiter="\t"),
            min_samples=args.min_samples,
            expected_interval_seconds=args.interval,
        )

    print("result={}".format("PASS" if report.passed else "FAIL"))
    print("samples={}".format(report.samples))
    print("duration_seconds={}".format(report.duration_seconds))
    print("rss_kb={}..{}".format(report.min_rss_kb, report.max_rss_kb))
    print(
        "max_cpu_percent_one_core={:.3f}".format(
            report.max_cpu_percent_one_core
        )
    )
    print("log_growth_kb={}".format(report.log_growth_kb))
    print("app_growth_kb={}".format(report.app_growth_kb))
    print("rx_error_delta={}".format(report.rx_error_delta))
    print("tx_error_delta={}".format(report.tx_error_delta))
    for warning in report.warnings:
        print("WARNING: {}".format(warning))
    for error in report.errors:
        print("ERROR: {}".format(error))
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
