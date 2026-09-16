"""Copy this repo's connectors, endpoints and metric repointing into moonshot-data.

`moonshot-data/` is an upstream clone that `python -m moonshot -i moonshot-data`
will happily delete and re-fetch. Anything of ours left only in there is one
reinstall away from gone, and it would not be reviewable in a diff either. So
the authoritative copies live here and this script installs them.

It is idempotent. Run it after any `-i moonshot-data`, and after editing a
connector.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "moonshot-data"

# Upstream points every LLM-as-judge metric at OpenAI, Azure or Together. We
# hold none of those keys and do hold Bedrock, so the judge is repointed. The
# value on the right is what upstream used, kept here so the report can say
# exactly what was substituted rather than "a different judge".
JUDGE_REPOINT = {
    "mlcprv-annotator": "openai-gpt4o",
    "mlcncr-annotator": "openai-gpt4o",
    "mlcvcr-annotator": "openai-gpt4o",
    "mlcipv-annotator": "openai-gpt4o",
    "cybersecevalannotator2": "openai-gpt4o",
    "answercarefully-annotator": "openai-gpt4o",
    "llamaguardannotator": "together-llama-guard-2-mlccommons",
    "gpt4annotator": "llm-judge-openai-gpt4-annotator",
    "cybersecevalannotator": "llm-judge-azure-gpt4-annotator",
}
JUDGE_ENDPOINT = "bedrock-claude-judge"


def main() -> int:
    if not DATA.is_dir():
        print(f"{DATA} not found — run `python -m moonshot -i moonshot-data` first")
        return 1

    for kind in ("connectors", "connectors-endpoints"):
        for source in sorted((ROOT / kind).iterdir()):
            shutil.copy2(source, DATA / kind / source.name)
            print(f"installed {kind}/{source.name}")

    config_path = DATA / "metrics" / "metrics_config.json"
    # Keep one pristine copy, so the diff between upstream and ours stays
    # visible after the first run overwrites the original.
    pristine = config_path.with_suffix(".json.upstream")
    if not pristine.exists():
        shutil.copy2(config_path, pristine)

    config = json.loads(pristine.read_text())
    for metric, was in JUDGE_REPOINT.items():
        if metric in config:
            config[metric]["endpoints"] = [JUDGE_ENDPOINT]
            print(f"repointed {metric}: {was} -> {JUDGE_ENDPOINT}")
    config_path.write_text(json.dumps(config, indent=4) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
