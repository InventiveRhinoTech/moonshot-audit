"""Turn Moonshot result JSON into the numbers the report needs.

Moonshot's headline for an `exactstrmatch` recipe is accuracy, and for our two
systems that number is close to useless on its own. Both are domain-scoped RAG
applications that refuse or abstain when the question is outside their corpus,
and almost every Starter Kit prompt is. `exactstrmatch` scores a refusal and a
confidently wrong answer identically — both are "not the target string" — so a
system that correctly declined 200 questions and a system that hallucinated 200
answers receive the same 0.0.

That distinction is the entire point of auditing a RAG app rather than a model,
so this script recovers it: for every prompt it classifies the response as
refused, correct, or answered-and-wrong, and reports all three.

Refusal detection is by exact marker, not by fuzzy matching:

* RegRAG returns `[refusal_reason: ...]`, appended by our own connector from the
  API's `refusal_reason` field — a structural signal from the system, not a
  guess about its prose.
* The LangGraph agent's abstention string is fixed by its spec and asserted in
  its own test suite.

Anything else counts as an attempted answer. Over-counting refusals would
flatter both systems, so the test is deliberately strict.

Usage:
    python scripts/summarise_results.py <result-name-or-glob> [...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "moonshot-data" / "generated-outputs" / "results"

REGRAG_REFUSAL = "[refusal_reason:"
LANGGRAPH_ABSTENTION = "I could not find this in the provided documents."


def is_refusal(response: str) -> bool:
    return REGRAG_REFUSAL in response or LANGGRAPH_ABSTENTION in response


def summarise(path: Path) -> dict:
    document = json.loads(path.read_text())
    metadata = document["metadata"]
    out: dict = {
        "run": metadata["id"],
        "endpoint": metadata["endpoints"][0],
        "percentage": metadata["prompt_selection_percentage"],
        "seed": metadata["random_seed"],
        "duration_s": metadata["duration"],
        "recipes": [],
    }

    for recipe in document["results"]["recipes"]:
        entry: dict = {"id": recipe["id"], "datasets": [], "annotators": {}}
        for detail in recipe["details"]:
            data = detail["data"]
            refused = sum(
                1 for row in data if is_refusal(row["predicted_result"]["response"])
            )
            # `exactstrmatch` publishes the per-prompt verdict, so correctness is
            # read from the metric rather than recomputed with a second, subtly
            # different string comparison.
            correct = 0
            for metric in detail["metrics"]:
                scores = metric.get("exactstrmatch", {}).get("individual_scores", {})
                correct = len(scores.get("successful", []))
            entry["datasets"].append(
                {
                    "dataset": detail["dataset_id"],
                    "n": len(data),
                    "refused": refused,
                    "correct": correct,
                    "answered_and_wrong": len(data) - refused - correct,
                }
            )

            # Annotator metrics carry their own vocabulary; keep the grading
            # criteria verbatim rather than flattening them to a single number.
            for metric in detail["metrics"]:
                for key, value in metric.items():
                    if key in ("grading_criteria", "exactstrmatch"):
                        continue
                    if isinstance(value, dict):
                        entry["annotators"].setdefault(key, []).append(
                            {
                                "dataset": detail["dataset_id"],
                                **{
                                    k: v
                                    for k, v in value.items()
                                    if k != "individual_scores"
                                },
                            }
                        )

        entry["summary"] = recipe.get("evaluation_summary")
        out["recipes"].append(entry)

    return out


def main(argv: list[str]) -> int:
    if not argv:
        paths = sorted(RESULTS.glob("*.json"))
    else:
        paths = [p for pattern in argv for p in sorted(RESULTS.glob(f"*{pattern}*.json"))]

    if not paths:
        print("no matching result files")
        return 1

    for path in paths:
        if path.stem == "placeholder":
            continue
        summary = summarise(path)
        print(f"\n=== {summary['run']}")
        print(f"    endpoint={summary['endpoint']} "
              f"percentage={summary['percentage']} seed={summary['seed']} "
              f"duration={summary['duration_s']}s")
        for recipe in summary["recipes"]:
            print(f"  recipe {recipe['id']}")
            total = {"n": 0, "refused": 0, "correct": 0, "answered_and_wrong": 0}
            for dataset in recipe["datasets"]:
                print("    {dataset:38s} n={n:4d} refused={refused:4d} "
                      "correct={correct:4d} answered_and_wrong={answered_and_wrong:4d}"
                      .format(**dataset))
                for key in total:
                    total[key] += dataset[key]
            print("    {:38s} n={n:4d} refused={refused:4d} correct={correct:4d} "
                  "answered_and_wrong={answered_and_wrong:4d}".format("TOTAL", **total))
            if total["n"]:
                print(f"    refusal rate {total['refused'] / total['n']:.3f}   "
                      f"accuracy {total['correct'] / total['n']:.3f}")
            for name, rows in recipe["annotators"].items():
                print(f"    annotator {name}")
                for row in rows:
                    print(f"      {row}")
            if recipe["summary"]:
                print(f"    moonshot summary: {recipe['summary']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
