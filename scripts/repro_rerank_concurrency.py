"""Minimal reproduction of the defect the Starter Kit run found in RegRAG.

Found by accident, which is the point: the first Hallucination run was
configured with `max_concurrency: 4` purely to finish faster, and RegRAG
answered some of those requests with HTTP 500. The traceback is

    File "/srv/app/rag/rerank.py", line 180, in score
        tokenizer.enable_truncation(max_length=MAX_PAIR_TOKENS)
    RuntimeError: Already borrowed

`_load()` caches one HuggingFace `tokenizers.Tokenizer` per process. FastAPI
runs a `def` (non-async) path operation in a threadpool, so two concurrent
`POST /v1/query` calls reach `score()` on different threads and both mutate that
one shared Rust object. `enable_truncation` takes a mutable borrow; if another
thread is inside `encode_batch` holding a borrow, the Rust side refuses and
raises. It is a data race guarded at runtime, not a model problem.

Nothing in RegRAG's own test suite or eval harness sends two queries at once, so
this had never been reached. No human types two questions simultaneously either
— it takes an unattended benchmark to find it.

Run with the audit override applied (rate limit raised), otherwise the 429s
arrive before the 500s:

    python scripts/repro_rerank_concurrency.py --concurrency 4 --requests 12
"""

from __future__ import annotations

import argparse
import asyncio
import collections

import httpx

# Deliberately in-corpus, so every request reaches the reranker rather than
# being short-circuited somewhere earlier. Varied, because identical questions
# produce identical candidate sets and therefore identical `encode_batch`
# durations: the threads line up and the race does not open. Different passage
# lengths are what stagger them.
QUESTIONS = [
    "How must a regulated entity report a cyber security incident to SEBI?",
    "What are the compliance officer requirements for OBPPs?",
    "What additional cash collateral is required?",
    "Which guidelines govern the handling of cybersecurity incidents?",
    "What must be reported through the SEBI Incident Reporting Portal?",
    "What are the timelines for incident reporting?",
]


async def one(client: httpx.AsyncClient, base_url: str, index: int) -> tuple[int, str]:
    question = QUESTIONS[index % len(QUESTIONS)]
    response = await client.post(f"{base_url}/v1/query", json={"question": question})
    detail = ""
    if response.status_code != 200:
        detail = response.text[:200]
    return response.status_code, detail


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--requests", type=int, default=12)
    args = parser.parse_args()

    semaphore = asyncio.Semaphore(args.concurrency)

    async def guarded(client: httpx.AsyncClient, index: int) -> tuple[int, str]:
        async with semaphore:
            return await one(client, args.base_url, index)

    async with httpx.AsyncClient(timeout=300) as client:
        results = await asyncio.gather(
            *(guarded(client, i) for i in range(args.requests))
        )

    counts = collections.Counter(status for status, _ in results)
    print(f"concurrency={args.concurrency} requests={args.requests}")
    for status, count in sorted(counts.items()):
        print(f"  HTTP {status}: {count}")
    for status, detail in results:
        if detail:
            print(f"  first non-200 body: {detail}")
            break

    # Non-zero exit when the defect reproduces, so this can gate a fix.
    return 1 if any(status != 200 for status, _ in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
