"""Recover a recipe's predictions from the runner's SQLite cache.

Needed because of how Moonshot handles a partially failed run. The MMLU run
against RegRAG attempted 174 prompts; 6 were rejected by RegRAG's own request
validation with HTTP 422 and never produced a response. The run finished with
status `completed_with_errors`, and its result file contains an empty `details`
list — not 168 scored prompts and 6 errors, but nothing at all.

The 168 successful predictions are not lost. They are in the runner's own
database, `generated-outputs/databases/<run-id>.db`, table `runner_cache_table`.
This reads them back and applies the same comparison `exactstrmatch` applies:
exact equality against the target, or membership if the target is a list.

Discarding 168 measured answers because 6 requests were malformed would be a
worse failure than the 422s. So they are recovered, and both numbers — what was
answered and what was rejected — go in the report.

Usage:
    python scripts/recover_from_cache.py <run-id-fragment>
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASES = ROOT / "moonshot-data" / "generated-outputs" / "databases"

REGRAG_REFUSAL = "[refusal_reason:"
LANGGRAPH_ABSTENTION = "I could not find this in the provided documents."


def is_refusal(response: str) -> bool:
    return REGRAG_REFUSAL in response or LANGGRAPH_ABSTENTION in response


def recover(path: Path) -> dict:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute("select * from runner_cache_table").fetchall()
    connection.close()

    by_dataset: dict[str, dict] = {}
    for row in rows:
        dataset = by_dataset.setdefault(
            row["dataset_id"],
            {"n": 0, "refused": 0, "correct": 0, "answered_and_wrong": 0,
             "refusal_reasons": {}},
        )
        response = json.loads(row["predicted_results"])["response"]
        target = row["target"]

        dataset["n"] += 1
        if is_refusal(response):
            dataset["refused"] += 1
            # RegRAG names which gate refused. Worth keeping: `below_threshold`
            # and `not_in_context` are different decisions and collapsing them
            # would hide which one is doing the work.
            marker = response.partition(REGRAG_REFUSAL)[2].partition("]")[0].strip()
            if marker:
                dataset["refusal_reasons"][marker] = (
                    dataset["refusal_reasons"].get(marker, 0) + 1
                )
        elif response == target or (isinstance(target, list) and response in target):
            dataset["correct"] += 1
        else:
            dataset["answered_and_wrong"] += 1

    return by_dataset


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1

    paths = [p for fragment in argv for p in sorted(DATABASES.glob(f"*{fragment}*.db"))]
    if not paths:
        print("no matching runner database")
        return 1

    for path in paths:
        print(f"\n=== {path.stem}")
        total = {"n": 0, "refused": 0, "correct": 0, "answered_and_wrong": 0}
        for dataset, counts in sorted(recover(path).items()):
            print("  {:32s} n={n:4d} refused={refused:4d} correct={correct:4d} "
                  "answered_and_wrong={answered_and_wrong:4d}".format(dataset, **counts))
            if counts["refusal_reasons"]:
                print(f"    refusal reasons: {counts['refusal_reasons']}")
            for key in total:
                total[key] += counts[key]
        print("  {:32s} n={n:4d} refused={refused:4d} correct={correct:4d} "
              "answered_and_wrong={answered_and_wrong:4d}".format("TOTAL", **total))
        if total["n"]:
            print(f"    refusal rate {total['refused'] / total['n']:.3f}   "
                  f"accuracy {total['correct'] / total['n']:.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
