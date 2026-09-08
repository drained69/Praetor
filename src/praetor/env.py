"""Automatic ``.env`` loading.

Any entry point (server, CLI, or ``python -c "from praetor ..."``) loads a
``.env`` file so credentials never have to be exported by hand. The file is
found by walking up from the current working directory. Variables already set
in the real environment are NOT overridden, so an explicit ``export`` still
wins. Secrets are never logged.
"""

from __future__ import annotations

import os
from pathlib import Path

_LOADED = False


def find_dotenv(start: Path | None = None) -> Path | None:
    """Return the nearest ``.env`` walking up from ``start`` (cwd by default)."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def _parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, _, value = line.partition("=")
    key = key.strip()
    if key.startswith("export "):
        key = key[len("export ") :].strip()
    value = value.strip().strip('"').strip("'")
    if not key:
        return None
    return key, value


def load_env(*, override: bool = False) -> bool:
    """Load the nearest ``.env`` once. Returns True if a file was applied."""
    global _LOADED
    if _LOADED:
        return False
    path = find_dotenv()
    if path is None:
        _LOADED = True
        return False
    try:  # prefer python-dotenv when available for full quoting/expansion support
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=str(path), override=override)
    except Exception:  # pragma: no cover - minimal fallback parser
        for raw in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_line(raw)
            if not parsed:
                continue
            key, value = parsed
            if override or key not in os.environ:
                os.environ[key] = value
    _LOADED = True
    return True
