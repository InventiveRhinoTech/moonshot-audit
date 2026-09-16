# moonshot-audit

The Moonshot working directory for **D-06** — auditing our own systems against
the IMDA Starter Kit for LLM-based App Testing, using the AI Verify Foundation's
[Project Moonshot](https://aiverify-foundation.github.io/moonshot/).

The spec is `case-studies/proposals/demand/D-06-PRD.md`; the report it produces
is `case-studies/proposals/evidence/starter-kit-audit.md`.

## What is committed and what is not

`moonshot-data/` and `moonshot-ui/` are upstream clones and are **not** committed
— `python -m moonshot -i moonshot-data` deletes and re-fetches them. Our files
live here and are copied in by `scripts/install_into_moonshot_data.py`:

| Path | What it is |
|---|---|
| `connectors/regrag-connector.py` | Model Connector for RegRAG's `POST /v1/query` |
| `connectors/langgraph-agent-connector.py` | Model Connector for the LangGraph agent's `POST /answer` |
| `connectors-endpoints/regrag-local.json` | endpoint config for the above |
| `connectors-endpoints/langgraph-agent-local.json` | endpoint config for the above |
| `connectors-endpoints/bedrock-claude-judge.json` | the LLM-as-judge every annotator metric was repointed at |
| `infra/regrag-audit-override.yml` | compose override raising RegRAG's rate limit for the run only |
| `scripts/` | env loader, installer, run driver, defect reproduction |
| `raw-results/` | run logs and result JSON kept as evidence |

## Setup, from nothing

Python **3.11 strictly**. `moonshot-data`'s requirements are marked
`python_version >= "3.11" and python_version < "3.12"`, and pip silently
*ignores* every one of them under any other version — the install appears to
succeed and then fails much later on a missing `nltk`.

```bash
uv python install 3.11
uv venv --python 3.11 venv
VIRTUAL_ENV=$PWD/venv uv pip install "aiverify-moonshot[all]" pip
source venv/bin/activate          # activate, do not just set VIRTUAL_ENV:
                                  # the installer shells out to whatever `pip`
                                  # is on PATH, and picks up the wrong Python
python -m moonshot -i moonshot-data -i moonshot-ui -u -o
python scripts/install_into_moonshot_data.py
python -m moonshot web            # UI http://localhost:3000, API :5000
```

## Running the Starter Kit

Bring up the target first, then:

```bash
export AWS_PROFILE=aws_rhino      # the judge runs on Bedrock
python scripts/run_starter_kit.py regrag-local hallucination
python scripts/run_starter_kit.py regrag-local data-disclosure
python scripts/run_starter_kit.py regrag-local adversarial
python scripts/run_starter_kit.py regrag-local undesirable
```

Results land in `moonshot-data/generated-outputs/results/`. Copy anything worth
keeping into `raw-results/`.
