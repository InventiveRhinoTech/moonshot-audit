"""Point the Moonshot APIs at this working directory.

`python -m moonshot web` reads `.env` for itself. A standalone script does not,
and the failure mode is unhelpful — `Unable to get defined object module
instance - None` from a storage read, which names neither the missing variable
nor the file it should have come from. So the same `.env` is parsed here and
handed to `api_set_environment_variables` explicitly.

Paths are resolved to absolute, because the values in `.env` are relative to the
repo root and a script run from `scripts/` would otherwise read an empty
connectors directory and report that nothing is installed.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load() -> dict[str, str]:
    """Parse `.env`, absolutise the paths, and register them with Moonshot."""
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split("#")[0].strip().strip('"').strip("'")
        if value.startswith("./"):
            value = str(ROOT / value[2:])
        env[key] = value

    from moonshot.api import api_set_environment_variables

    api_set_environment_variables(env)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    return env
