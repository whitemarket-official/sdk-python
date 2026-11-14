"""Partner Token lookup: the environment, then the git-ignored dotenv file of the repo root."""

import os
from pathlib import Path

ENV_VARIABLE = "WHITEMARKET_PARTNER_TOKEN"
DOTENV_FILE = Path(__file__).resolve().parents[2] / (".env")


def dotenv_value(text: str, key: str) -> str | None:
    """`KEY=value` from dotenv text: comments, blank lines, `export`, single or double quotes.

    No variable expansion. A small parser instead of a dotenv dependency (CLAUDE.md rule 10).
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").lstrip()
        name, separator, value = line.partition("=")
        if not separator or name.strip() != key:
            continue
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"":
            return value[1:-1]
        return value.split(" #", 1)[0].rstrip()
    return None


def partner_token() -> str | None:
    """The token or None. The value is never printed or logged by this module."""
    token = os.environ.get(ENV_VARIABLE, "")
    if not token and DOTENV_FILE.is_file():
        token = dotenv_value(DOTENV_FILE.read_text(encoding="utf-8"), ENV_VARIABLE) or ""
    return token or None
