"""Run IMDA Starter Kit recipes against one of our systems and save the raw result.

Why recipes and not `run_cookbooks`: `prompt_selection_percentage` is a single
number applied to every dataset in the run. The Hallucination cookbook mixes
`mmlu-all` (17,487 prompts) with `singapore-public-housing` (12), so any
percentage that keeps MMLU affordable reduces the Singapore sets to the
`max(1, ...)` floor and any percentage that makes the Singapore sets meaningful
makes MMLU a multi-hour Bedrock bill. Running the cookbooks' own recipes with a
per-recipe percentage is the same tests at a sample size that can be stated.

The recipes, percentages and seed are all recorded in the result file, so a run
is reproducible from the report alone.

Usage:
    python scripts/run_starter_kit.py <endpoint-id> <risk> [--percentage N]

    risk: hallucination | data-disclosure | adversarial | undesirable
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import msenv  # noqa: E402

# Recipe -> prompt_selection_percentage, per Starter Kit risk.
#
# 100 wherever the dataset is small enough to run whole, because a sampled run
# of a 76-prompt set is a worse number than the complete one and costs the same
# order of money.
RISKS: dict[str, list[tuple[str, int]]] = {
    "hallucination": [
        ("singapore-facts-tf", 100),   # 200 prompts across 3 datasets
        ("singapore-facts-mcq", 100),  # 76 prompts across 4 datasets
        ("mmlu", 1),                   # 174 of 17,487
    ],
    "data-disclosure": [
        ("mlc-prv-en", 100),           # 100 prompts
    ],
    "adversarial": [
        ("cyberseceval-en", 100),      # 251 prompt-injection attempts
    ],
    # `real-toxicity-prompts-completion` is deliberately absent: its dataset is
    # 198,884 prompts, and even 1% is 1,988 live calls. Its exclusion is a cost
    # bound, not a capability gap, and section 6 of the report says so.
    "undesirable": [
        ("singapore-safety", 100),     # 59 prompts
        ("mlc-vcr-en", 25),
        ("mlc-ncr-en", 25),
        ("mlc-ailuminate-cse", 25),
        ("mlc-ailuminate-hte", 25),
        ("mlc-ailuminate-iwp", 25),
        ("mlc-ailuminate-ncr", 25),
        ("mlc-ailuminate-spc-ele", 25),
        ("mlc-ailuminate-spc-fin", 25),
        ("mlc-ailuminate-spc-hlt", 25),
        ("mlc-ailuminate-spc-lgl", 25),
        ("mlc-ailuminate-src", 25),
        ("mlc-ailuminate-ssh", 25),
        ("mlc-ailuminate-sxc-prn", 25),
        ("mlc-ailuminate-vcr", 25),
    ],
}

# The same plan, sampled down, for a target that cannot afford the full one.
#
# The LangGraph agent takes ~37s per benchmark prompt, not the ~6s an in-corpus
# question takes. Almost every Starter Kit prompt is outside its two-corpus
# world, so the grader calls the evidence weak every time and the agent spends
# its entire rewrite budget — six or more Groq calls — before abstaining. The
# full plan is twelve hours of that. This one is about three.
#
# Because `random.sample` is seeded and a 100% run is `range(n)` rather than a
# sample, every prompt drawn here is also in the full run. So a system measured
# on SMALL and a system measured on the full plan can still be compared
# directly, on the intersection — see `scripts/compare_runs.py`.
SMALL: dict[str, int] = {
    "singapore-facts-tf": 10,
    "singapore-facts-mcq": 25,
    "mmlu": 1,
    "mlc-prv-en": 25,
    "cyberseceval-en": 20,
    "singapore-safety": 25,
}
SMALL_DEFAULT = 5

RANDOM_SEED = 20260916


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("endpoint")
    parser.add_argument("risk", choices=sorted(RISKS))
    parser.add_argument("--plan", choices=("full", "small"), default="full")
    parser.add_argument("--percentage", type=int, default=None,
                        help="override every recipe's percentage in this risk")
    parser.add_argument("--only", default=None, help="run a single recipe id")
    args = parser.parse_args()

    msenv.load()
    from moonshot.api import api_create_runner, api_load_runner, api_get_all_runner_name

    plan = RISKS[args.risk]
    if args.only:
        plan = [(r, p) for r, p in plan if r == args.only]
        if not plan:
            print(f"no recipe {args.only} under {args.risk}")
            return 1
    if args.plan == "small":
        plan = [(r, SMALL.get(r, SMALL_DEFAULT)) for r, _ in plan]
    if args.percentage is not None:
        plan = [(r, args.percentage) for r, _ in plan]

    for recipe, percentage in plan:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"{args.endpoint}-{args.risk}-{recipe}-{stamp}"
        print(f"\n=== {name}  ({percentage}% of each dataset, seed {RANDOM_SEED})",
              flush=True)

        # A runner owns its own SQLite database, so one per recipe keeps a
        # failed recipe from taking the completed ones down with it.
        if name in api_get_all_runner_name():
            runner = api_load_runner(name)
        else:
            runner = api_create_runner(name=name, endpoints=[args.endpoint])

        # `run_recipes` and `close` are both coroutines despite their `-> None`
        # annotations; calling them bare returns immediately and the run appears
        # to succeed having done nothing.
        async def execute() -> None:
            try:
                await runner.run_recipes(
                    recipes=[recipe],
                    prompt_selection_percentage=percentage,
                    random_seed=RANDOM_SEED,
                )
            finally:
                await runner.close()

        asyncio.run(execute())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
