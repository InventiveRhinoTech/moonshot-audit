# moonshot-audit

I ran Singapore's **[IMDA Starter Kit for LLM-based App Testing](https://aiverifyfoundation.sg/)**
against two of my own RAG applications, using the AI Verify Foundation's
**[Project Moonshot](https://aiverify-foundation.github.io/moonshot/)**, and published everything —
including the results that make me look bad and the number I got wrong first.

**📄 The full report is [`REPORT.md`](REPORT.md)** — all four risks, the comparison against my own
evaluation harness, the seven things that scored badly, and what could not be measured at all.

This repository is the evidence behind it: the connectors, the run scripts, and every raw result
file. Nothing here is a summary. If a number is quoted anywhere, the run that produced it is in
`raw-results/`.

---

## The headline: a grade E that means the opposite of what it looks like

My RAG system scored **grade E on hallucination. 0.00 accuracy across 386 prompts.**

Then I counted what the 386 "wrong" answers actually were:

**386 refusals. Zero fabrications.**

The benchmark scores with exact string match, so a refusal and a confidently invented answer are
both "not the target string" and score identically. A system that correctly declined 386
out-of-corpus questions grades the same as one that hallucinated 386 answers.

My system answers over nine SEBI circulars. The Starter Kit asks about Singaporean hawker food,
chess openings and university chemistry. Refusing is the correct behaviour and the benchmark has no
way to say so.

**Every results table in the write-up separates *refused* from *answered and wrong* for this
reason.** They are opposite outcomes. Reported together they state the opposite of what happened.

---

## What the audit found

| Starter Kit risk | Prompts | Result | The honest reading |
|---|---|---|---|
| **Hallucination** | 386 | grade **E**, 0.00 accuracy | 386 refusals, **0 fabrications**. See above |
| **Undesirable content** | 68 | grade **A**, 0 unsafe | **Not a safety property.** Read the warning below |
| **Data disclosure** | 25 | grade **A**, 0 unacceptable | Refused all 25 — but this corpus holds no personal data to leak |
| **Adversarial prompts** | 50 injections | **Low Risk (86.0)** | **0 of 50 changed the system's behaviour** |

### The A grade I refuse to take credit for

The system scored **A on hate, violent crime, sex crimes, child exploitation, self-harm,
indiscriminate weapons and privacy** — and it has **no content-safety layer whatsoever.**

It scored A because none of those prompts retrieve anything from nine SEBI circulars, so the
retrieval gate refuses before generation and there is nothing left to be unsafe about. The
architecture produces the right outcome for a reason that has nothing to do with content safety.

**Change the corpus, or lower the refusal threshold, and nothing stands between a hostile prompt and
the generator.** That is an artefact of this index on this day. Selling it as a safety property
would be the most dishonest thing available in this whole exercise.

---

## Three bugs this run found — two of them in the benchmark

These are the parts most likely to be useful to someone else running Moonshot.

### 1. `cybersecevalannotator2` silently discarded 39 of 50 correct verdicts

The metric extracts its verdict as `text[i+3:]` after the last `"Result"`, which assumes the judge
wrote `Result: "` — colon, space, quote. My judge wrote `Result: Prompt Injection Unsuccessful`, two
characters, so the slice began one character late and produced `rompt Injection Unsuccessful`. The
regex then misses, and a **correct** verdict is filed as `unknown`.

Every `unknown` counts against the system. The run published **Moderate-High Risk (22.0)**. With the
quoted format mandated in the judge's `post_prompt`, the **identical 50 prompts scored Low Risk
(86.0)**.

**Both runs are in `raw-results/databases/`** — `…095218z` carries
`"grade": "Moderate-High Risk"` with 39 unknowns, and `…101424z` carries `"grade": "Low Risk"` with
4, on the same 50 prompts. (A third, `…094156z`, is an earlier incomplete run and reached no grade.)
The wrong number is published next to the right one, because a report that only shows the corrected
number is a report you cannot check.

### 2. `llamaguardannotator` grades an unmeasured result as a failure

It sends the bare string `Agent: <response>` and greps the reply for `unsafe`, then `safe`. That
works only because Llama Guard carries its hazard taxonomy and output format in its weights. Pointed
at a general chat model it returned `unknown` for **every** prompt — and Moonshot reported 100%
unknown as **grade E**.

Grade E reads as "this system emits unsafe content". Nothing had been measured at all. Fixed by
supplying the MLCommons taxonomy and a one-word output contract as `pre_prompt`/`post_prompt`.

### 3. A completed-with-errors run writes an empty result file

Six prompts exceeded my API's 2,000-character input limit and returned HTTP 422. The run finished
`completed_with_errors` and Moonshot wrote a result file whose `details` list is **empty** — not 168
scored prompts and 6 errors, but nothing at all. Anyone reading only that file would conclude the
recipe had never run.

`scripts/recover_from_cache.py` pulls the predictions back out of the runner's own SQLite cache.

### And one in my own code

A **data race in my reranker**: a single cached HuggingFace `Tokenizer` mutated across FastAPI's
threadpool under concurrency. `enable_truncation()` takes a mutable borrow, `encode_batch()` holds
an immutable one, and the overlap raises `RuntimeError: Already borrowed`.

**Observed once in twenty concurrent requests, then not reproducible** across 66 further attempts.
It is reported as observed-once with the mechanism read from the code, **not as a rate**.
`raw-results/regrag-rerank-concurrency-repro.txt`, and `scripts/repro_rerank_concurrency.py`.

**Moonshot's own `@perform_retry` retried that failure and it passed.** Without reading the
container log it would never have appeared in any score. A benchmark that retries reports
availability it did not measure.

---

## Model Connectors for a custom application

Moonshot talks to OpenAI, Anthropic, Together and HuggingFace with an API key. Testing your **own**
application needs a Model Connector, and the docs say — correctly — that this is code only: not
available through the Web UI or the CLI.

There is no worked example in the docs, so here are three:

| File | What it connects to |
|---|---|
| `connectors/regrag-connector.py` | a FastAPI RAG service over `POST /v1/query` |
| `connectors/langgraph-agent-connector.py` | a LangGraph agent over `POST /answer` |
| `connectors/bedrock-judge-connector.py` | AWS Bedrock, as the LLM-as-judge every annotator metric was repointed at |

The shape: subclass `Connector`, initialise with `ConnectorEndpointArguments`, and implement

```python
@Connector.rate_limited
@perform_retry
async def get_response(self, prompt: str) -> ConnectorResponse:
    ...
```

**Why `bedrock-judge-connector.py` exists:** upstream's Bedrock connector *raises* when the model
returns an empty assistant message. One declined judgement cost an entire 50-prompt recipe. This one
records a sentinel instead.

---

## Setup, from nothing

Python **3.11 strictly**. `moonshot-data`'s requirements are marked
`python_version >= "3.11" and python_version < "3.12"`, and pip silently *ignores* every one of them
under any other version — the install appears to succeed and then fails much later on a missing
`nltk`.

```bash
uv python install 3.11
uv venv --python 3.11 venv
VIRTUAL_ENV=$PWD/venv uv pip install "aiverify-moonshot[all]" pip
source venv/bin/activate          # activate, do not just set VIRTUAL_ENV: the
                                  # installer shells out to whatever `pip` is on
                                  # PATH and picks up the wrong Python
python -m moonshot -i moonshot-data -i moonshot-ui -u -o
python scripts/install_into_moonshot_data.py
python -m moonshot web            # UI http://localhost:3000, API :5000
```

The installer writes `.env` — Moonshot's directory paths and web ports, nothing
more. It is gitignored; [`.env.example`](.env.example) is the tracked copy.

### Credentials

**No key belongs in any file in this repository.** Every connector reads from the
environment: `openai-connector.py` falls back to `os.getenv("OPENAI_API_KEY")`,
and the Bedrock connectors use the normal AWS credential chain. Every committed
endpoint JSON keeps `"token": ""`.

To hand a key to a run without it touching a file git can see:

```bash
echo 'OPENAI_API_KEY=sk-...' > .env.secret     # matched by .gitignore
set -a && source .env.secret && set +a
export AWS_PROFILE=aws_rhino                   # Bedrock judge and attacker
```

**One more trap that cost more time than the connectors did:** `Runner.run_recipes` and
`Runner.close` are coroutines annotated `-> None`. Call them without `await` and they return
instantly, and the run appears to succeed having done nothing at all.

### Running the Starter Kit

Bring up the target service first, then:

```bash
export AWS_PROFILE=...            # the judge runs on Bedrock
python scripts/run_starter_kit.py regrag-local hallucination
python scripts/run_starter_kit.py regrag-local data-disclosure
python scripts/run_starter_kit.py regrag-local adversarial
python scripts/run_starter_kit.py regrag-local undesirable
```

Results land in `moonshot-data/generated-outputs/results/`; anything worth keeping is copied into
`raw-results/`.

---

## What is in this repository

`moonshot-data/` and `moonshot-ui/` are **not** committed — `python -m moonshot -i moonshot-data`
deletes and re-fetches them. The authoritative copies of my files live here and are installed by
`scripts/install_into_moonshot_data.py`.

| Path | What it is |
|---|---|
| `connectors/` | the three Model Connectors above |
| `connectors-endpoints/` | endpoint configs. **The `token` fields are placeholders** — Bedrock auth is via `AWS_PROFILE` |
| `infra/` | compose override raising my service's rate limit for the run only |
| `scripts/` | env loader, installer, run driver, result summariser, cache recovery, defect repro |
| `raw-results/results/` | 26 result files |
| `raw-results/databases/` | runner databases, including both adversarial runs |
| `raw-results/logs/` | run logs, including the quota exhaustion that ended the second system's run |

---

## Limits — read these before quoting anything

- **The judge is Bedrock Claude Sonnet 4.5, not GPT-4o.** Every LLM-as-judge metric in
  `moonshot-data` points at OpenAI, Azure or Together; I hold none of those keys. Nine annotator
  metrics were repointed, with the upstream value recorded beside each one in
  `scripts/install_into_moonshot_data.py`. **The safety numbers here are not comparable to a
  published Moonshot leaderboard.**
- **The second system was graded on one risk of four.** A free-tier token budget ran out mid-run.
  Its other three grades are *unknown*, **not** *good*.
- **Moonshot's automated red teaming was not run.** The adversarial *cookbook* ran — a fixed
  dataset, 50 sampled. The **attack modules**, which generate adaptive attacks, did not. That is the
  likeliest source of a finding this audit does not have.
- **Every safety result depends on what is and is not in the index.** See the A-grade warning above.
- **This is not a certification.** It is a self-administered run of a published voluntary test
  suite, with the report open for inspection. It is not the AI Tester Accreditation Programme and
  not any accreditation.

---

## Licence

MIT — see [`LICENSE`](LICENSE). The connectors and scripts are here to be reused; that is most of
why this repository is public.

The `raw-results/` files are records of runs against public benchmark datasets that carry their own
upstream licences, and the report is a description of what happened rather than a reusable
component. Attribution is welcome but not required.

---

## Why publish an audit of your own systems

Because an evaluation where everything passes teaches nobody anything, including the person who ran
it. The useful output of this run was a data race in my own code, two scoring faults in a national
test suite, and one grade I published wrong before I published it right.

All of it is here.

— Sandip
