"""Copy this repo's connectors, endpoints and metric repointing into moonshot-data.

`moonshot-data/` is an upstream clone that `python -m moonshot -i moonshot-data`
will happily delete and re-fetch. Anything of ours left only in there is one
reinstall away from gone, and it would not be reviewable in a diff either. So
the authoritative copies live here and this script installs them.

It is idempotent. Run it after any `-i moonshot-data`, and after editing a
connector.
"""

from __future__ import annotations

import argparse
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
    "answercarefully-annotator": "openai-gpt4o",
    "gpt4annotator": "llm-judge-openai-gpt4-annotator",
    "cybersecevalannotator": "llm-judge-azure-gpt4-annotator",
}
JUDGE_ENDPOINT = "bedrock-claude-judge"

# `llamaguardannotator` gets its own endpoint rather than the general judge.
# It sends the bare string "Agent: <response>" and greps the reply for "unsafe"
# then "safe", which only works against a model carrying Llama Guard's taxonomy
# and output format in its weights. Pointed at a general chat model it returns
# `unknown` for every prompt — and Moonshot reports 100% unknown as grade E,
# which reads as "this system emits unsafe content" when nothing was measured.
# The stand-in endpoint supplies that taxonomy and output contract as prompts.
LLAMA_GUARD_METRIC = "llamaguardannotator"
LLAMA_GUARD_ENDPOINT = "bedrock-claude-llamaguard"

# `--safeguard` swaps that stand-in for a *purpose-built* safety classifier.
# Bedrock does not host Meta's Llama Guard, but it does host OpenAI's
# `gpt-oss-safeguard-120b`, which is the same class of model: trained to emit a
# safety verdict rather than to converse. That matters because 4b of the report
# measured what a judge swap costs — the same 25 responses scored A under one
# judge and B under another — so a general chat model wearing a taxonomy in its
# prompt is the weakest link in section 3.2's A grades.
#
# Still a substitution, and still disclosed: it is not Llama Guard, so these
# numbers remain not directly comparable to a published Moonshot leaderboard.
# It is a better one, and it is a second independent opinion on the risk where
# there had only ever been one.
SAFEGUARD_ENDPOINT = "bedrock-safeguard-llamaguard"

# `cybersecevalannotator2` needs its own endpoint for the same class of reason.
# It slices the judge's reply as text[i+3:] after the last "Result", which
# assumes `Result: "` — colon, space, quote. A judge that writes
# `Result: Prompt Injection Unsuccessful` loses its first character to the
# offset and the metric files a correct verdict as unknown. Its endpoint's
# post_prompt mandates the quoted form the extractor expects.
CYBERSECEVAL_METRIC = "cybersecevalannotator2"
CYBERSECEVAL_ENDPOINT = "bedrock-claude-cyberseceval"

# Two of the fifteen attack modules drive an *attacker* LLM rather than
# perturbing the prompt locally, and both are configured for `openai-gpt4`.
# Same substitution as the judges, and it matters more here: this model writes
# the attacks, so its willingness to play a hostile persona bounds how hard the
# red teaming actually pushes. The report says which model wrote the attacks.
ATTACKER_REPOINT = {
    "malicious_question_generator": "openai-gpt4",
    "violent_durian": "openai-gpt4",
}
ATTACKER_ENDPOINT = "bedrock-claude-attacker"

# `--with-openai` leaves everything upstream assigns to OpenAI pointing at
# OpenAI, and only substitutes what genuinely has nowhere else to go. Run it
# when an OPENAI_API_KEY is exported; the endpoint files ship with `"token": ""`
# and `openai-connector.py` falls back to `os.getenv("OPENAI_API_KEY")`, so no
# key is written anywhere.
#
# Two things stay on Bedrock even then, because neither is an OpenAI endpoint
# upstream: `llamaguardannotator` wants Llama Guard on Together, and
# `cybersecevalannotator` wants Azure. Both remain disclosed substitutions.
STAYS_SUBSTITUTED_WITH_OPENAI = {"cybersecevalannotator"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-openai", action="store_true",
        help="keep upstream's OpenAI judges and attackers instead of Bedrock",
    )
    parser.add_argument(
        "--safeguard", action="store_true",
        help="judge undesirable content with gpt-oss-safeguard rather than Claude",
    )
    args = parser.parse_args()

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
        if metric not in config:
            continue
        if args.with_openai and metric not in STAYS_SUBSTITUTED_WITH_OPENAI:
            config[metric]["endpoints"] = [was]
            print(f"kept upstream {metric}: {was}")
        else:
            config[metric]["endpoints"] = [JUDGE_ENDPOINT]
            print(f"repointed {metric}: {was} -> {JUDGE_ENDPOINT}")
    if LLAMA_GUARD_METRIC in config:
        was = "together-llama-guard-2-mlccommons"
        target = SAFEGUARD_ENDPOINT if args.safeguard else LLAMA_GUARD_ENDPOINT
        config[LLAMA_GUARD_METRIC]["endpoints"] = [target]
        print(f"repointed {LLAMA_GUARD_METRIC}: {was} -> {target}")
    if CYBERSECEVAL_METRIC in config:
        if args.with_openai:
            config[CYBERSECEVAL_METRIC]["endpoints"] = ["openai-gpt4o"]
            print(f"kept upstream {CYBERSECEVAL_METRIC}: openai-gpt4o")
        else:
            config[CYBERSECEVAL_METRIC]["endpoints"] = [CYBERSECEVAL_ENDPOINT]
            print(f"repointed {CYBERSECEVAL_METRIC}: openai-gpt4o -> {CYBERSECEVAL_ENDPOINT}")
    config_path.write_text(json.dumps(config, indent=4) + "\n")

    attack_config_path = DATA / "attack-modules" / "attack_modules_config.json"
    attack_pristine = attack_config_path.with_suffix(".json.upstream")
    if not attack_pristine.exists():
        shutil.copy2(attack_config_path, attack_pristine)

    attack_config = json.loads(attack_pristine.read_text())
    for module, was in ATTACKER_REPOINT.items():
        if module not in attack_config:
            continue
        if args.with_openai:
            attack_config[module]["endpoints"] = [was]
            print(f"kept upstream attack module {module}: {was}")
        else:
            attack_config[module]["endpoints"] = [ATTACKER_ENDPOINT]
            print(f"repointed attack module {module}: {was} -> {ATTACKER_ENDPOINT}")
    attack_config_path.write_text(json.dumps(attack_config, indent=4) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
