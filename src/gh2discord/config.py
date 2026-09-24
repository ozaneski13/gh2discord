from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

WEBHOOK_RE = re.compile(
    r"^https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+$"
)
API_VERSION_RE = re.compile(r"(discord(?:app)?\.com/api)/v\d+/")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ConfigError(Exception):
    pass


def config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "gh2discord" / "config.json"


def normalize_webhook_url(url: str) -> str:
    url = url.strip().rstrip("/")
    url = API_VERSION_RE.sub(r"\1/", url)
    if url.endswith("/github"):
        url = url[: -len("/github")]
    if not WEBHOOK_RE.match(url):
        raise ConfigError(
            "not a Discord webhook URL "
            "(expected https://discord.com/api/webhooks/<id>/<token>)"
        )
    return url


def normalize_repo(repo: str) -> str:
    repo = repo.strip().rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "github.com/", "git@github.com:"):
        if repo.startswith(prefix):
            repo = repo[len(prefix):]
            break
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not REPO_RE.match(repo):
        raise ConfigError(f"'{repo}' is not a valid owner/repo reference")
    return repo


def _empty() -> dict:
    return {"version": 1, "default_channel": None, "channels": {}, "repos": {}}


def _validate(data: dict, path: Path) -> None:
    channels = data["channels"]
    if not isinstance(channels, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in channels.items()
    ):
        raise ConfigError(f"config at {path} is corrupt: 'channels' must map names to URLs")
    repos = data["repos"]
    if not isinstance(repos, dict) or not all(
        isinstance(k, str) and isinstance(v, dict) for k, v in repos.items()
    ):
        raise ConfigError(f"config at {path} is corrupt: 'repos' must map repos to records")
    default = data["default_channel"]
    if default is not None and not isinstance(default, str):
        raise ConfigError(
            f"config at {path} is corrupt: 'default_channel' must be a channel name or null"
        )


def load(path: Path | None = None) -> dict:
    path = path or config_path()
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read config at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config at {path} is not a JSON object")
    for key, default in _empty().items():
        data.setdefault(key, default)
    _validate(data, path)
    return data


def save(cfg: dict, path: Path | None = None) -> Path:
    path = path or config_path()
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.unlink(missing_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(cfg, indent=2) + "\n")
        tmp.replace(path)
    except OSError as exc:
        raise ConfigError(f"cannot write config at {path}: {exc}") from exc
    return path
