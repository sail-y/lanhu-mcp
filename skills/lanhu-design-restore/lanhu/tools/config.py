"""Skill configuration: cookie lookup and .env loading."""
from __future__ import annotations

import os
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_FILE = SKILL_ROOT / ".env"
COOKIE_ENV = "LANHU_COOKIE"


def _parse_dotenv(path: Path) -> dict:
    env: dict = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env[key] = value
    return env


def load_dotenv() -> bool:
    if not ENV_FILE.exists():
        return False
    try:
        dotenv = _parse_dotenv(ENV_FILE)
    except Exception as exc:
        print(f"[WARN] Failed to read {ENV_FILE}: {exc}")
        return False
    for k, v in dotenv.items():
        os.environ.setdefault(k, v)
    return bool(dotenv)


def get_cookie() -> str:
    cookie = os.environ.get(COOKIE_ENV)
    if not cookie:
        raise SystemExit(
            f"[FAIL] {COOKIE_ENV} is missing. Set it via environment variable "
            f"or the skill-local .env ({ENV_FILE})."
        )
    return cookie
