from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import ConfigError, normalize_webhook_url
from .github import GitHubClient, GitHubError

GITHUB_SUFFIX = "/github"
DEFAULT_EVENTS = (
    "issue_comment",
    "issues",
    "pull_request",
    "pull_request_review",
    "push",
    "release",
)


@dataclass
class TrackResult:
    repo: str
    channel: str
    action: str
    hook_id: int
    events: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def parse_events(spec: str) -> list:
    events = set()
    for name in (e.strip() for e in spec.split(",")):
        keyword = name.lower()
        if keyword in ("all", "*"):
            events.add("*")
        elif keyword == "default":
            events.update(DEFAULT_EVENTS)
        elif name:
            events.add(name)
    if not events:
        raise ConfigError("no events given")
    return sorted(events)


def resolve_channel(cfg: dict, name: str | None = None):
    if name is None:
        name = cfg.get("default_channel")
        if not name:
            raise ConfigError(
                "no default channel configured; add one first:\n"
                "  gh2discord channel add <name> <discord-webhook-url> --default"
            )
    url = cfg["channels"].get(name)
    if not url:
        raise ConfigError(f"unknown channel '{name}'; see: gh2discord channel list")
    return name, url


def channel_add(cfg: dict, name: str, url: str, make_default: bool = False) -> bool:
    name = name.strip()
    if not name:
        raise ConfigError("channel name must be non-empty")
    canonical = normalize_webhook_url(url)
    cfg["channels"][name] = canonical
    if make_default or not cfg.get("default_channel"):
        cfg["default_channel"] = name
    return cfg["default_channel"] == name


def channel_remove(cfg: dict, name: str) -> None:
    if name not in cfg["channels"]:
        raise ConfigError(f"unknown channel '{name}'")
    used_by = [r for r, rec in cfg["repos"].items() if rec.get("channel") == name]
    if used_by:
        raise ConfigError(
            f"channel '{name}' is still used by: {', '.join(sorted(used_by))}. "
            "Untrack them or retrack with another channel first."
        )
    del cfg["channels"][name]
    if cfg.get("default_channel") == name:
        cfg["default_channel"] = next(iter(sorted(cfg["channels"])), None)


def channel_default(cfg: dict, name: str) -> None:
    if name not in cfg["channels"]:
        raise ConfigError(f"unknown channel '{name}'")
    cfg["default_channel"] = name


def _discord_hooks(hooks: list) -> list:
    result = []
    for hook in hooks:
        url = (hook.get("config") or {}).get("url", "")
        if isinstance(url, str) and "/api/webhooks/" in url:
            result.append(hook)
    return result


def _hook_ids(hooks: list) -> str:
    return ", ".join(str(h["id"]) for h in hooks)


def _shell_arg(value: str) -> str | None:
    if re.fullmatch(r"[\w.-]+", value):
        return value
    if set(value) & set('"$`!\\“”„') or re.search(r"%[^%]+%", value):
        return None
    return f'"{value}"'


def all_events_warning(cfg: dict, repo: str, hook_id: int, channel: str | None) -> str:
    lines = [
        f"warning: {repo} hook {hook_id} sends every GitHub event (*)",
        "  CI bursts (check_run, check_suite, workflow_job) hit Discord's rate limit "
        "(HTTP 429) and drop real notifications",
    ]
    if channel is None:
        lines.append(
            "  gh2discord does not manage this hook; "
            "change its events in the repo's Settings -> Webhooks on GitHub"
        )
    else:
        flag = ""
        placeholder = False
        if channel != cfg.get("default_channel"):
            quoted = _shell_arg(channel)
            placeholder = quoted is None
            flag = f" --channel {'CHANNEL' if placeholder else quoted}"
        lines.append(
            f"  switch to the default events: gh2discord track {repo}{flag} --events default"
        )
        lines.append(
            f"  keep every event and silence this warning: "
            f"gh2discord track {repo}{flag} --events all"
        )
        if placeholder:
            lines.append(
                f"  replace CHANNEL with the channel name, quoted for your shell: {channel}"
            )
    return "\n".join(lines)


def _all_events_opt_in(record: dict, hook_id: int) -> bool:
    return record.get("all_events_opt_in") is True and record.get("hook_id") == hook_id


def _managed_hook_id(cfg: dict, record: dict, discord_hooks: list):
    ids = [h["id"] for h in discord_hooks]
    if record.get("hook_id") in ids:
        return record["hook_id"]
    if len(ids) == 1:
        return ids[0]
    default_url = cfg["channels"].get(cfg.get("default_channel"))
    for hook in discord_hooks:
        if default_url and hook["config"]["url"] == default_url + GITHUB_SUFFIX:
            return hook["id"]
    return None


def track(
    client: GitHubClient,
    cfg: dict,
    repo: str,
    channel: str | None = None,
    events: list | None = None,
    force: bool = False,
) -> TrackResult:
    name, base_url = resolve_channel(cfg, channel)
    target = base_url + GITHUB_SUFFIX
    previous = cfg["repos"].get(repo, {})
    hooks = client.list_hooks(repo)
    discord_hooks = _discord_hooks(hooks)
    exact = [h for h in discord_hooks if h["config"]["url"] == target]
    others = [h for h in discord_hooks if h["config"]["url"] != target]
    warnings = []

    if exact:
        hook = exact[0]
        final = events if events is not None else sorted(hook.get("events", []))
        same_config = (hook.get("config") or {}).get("content_type") == "json"
        same_events = sorted(hook.get("events", [])) == sorted(final)
        if same_config and same_events and hook.get("active", True):
            action = "unchanged"
        else:
            hook = client.update_hook(
                repo, hook["id"], target_url=target, events=final, active=True
            )
            action = "updated"
        if others:
            if force:
                for other in others:
                    client.delete_hook(repo, other["id"])
                warnings.append(
                    f"deleted {len(others)} other Discord hook(s): {_hook_ids(others)}"
                )
            else:
                warnings.append(
                    f"warning: {repo} also posts to {len(others)} other Discord hook(s) "
                    f"(ids {_hook_ids(others)}); re-run with --force to delete them"
                )
    elif others and not force:
        raise ConfigError(
            f"{repo} already posts to a different Discord webhook "
            f"(hook ids: {_hook_ids(others)}). "
            "Re-run with --force to retarget, or remove them on GitHub first."
        )
    elif others:
        final = events if events is not None else sorted(others[0].get("events", []))
        hook = client.update_hook(
            repo, others[0]["id"], target_url=target, events=final, active=True
        )
        action = "retargeted"
        for other in others[1:]:
            client.delete_hook(repo, other["id"])
        if len(others) > 1:
            warnings.append(
                f"deleted {len(others) - 1} extra Discord hook(s): {_hook_ids(others[1:])}"
            )
    else:
        final = events if events is not None else list(DEFAULT_EVENTS)
        hook = client.create_hook(repo, target, final)
        action = "created"

    record = {"channel": name, "hook_id": hook["id"], "events": final}
    if "*" in final:
        if events is not None or _all_events_opt_in(previous, hook["id"]):
            record["all_events_opt_in"] = True
        else:
            warnings.append(all_events_warning(cfg, repo, hook["id"], name))
    cfg["repos"][repo] = record
    return TrackResult(repo, name, action, hook["id"], final, warnings)


def untrack(client: GitHubClient, cfg: dict, repo: str) -> list:
    record = cfg["repos"].get(repo)
    hooks = client.list_hooks(repo)
    matched = []
    if record:
        matched = [h for h in hooks if h["id"] == record.get("hook_id")]
    if not matched:
        known_targets = {url + GITHUB_SUFFIX for url in cfg["channels"].values()}
        matched = [h for h in _discord_hooks(hooks) if h["config"]["url"] in known_targets]
    if not matched:
        cfg["repos"].pop(repo, None)
        return []
    for hook in matched:
        client.delete_hook(repo, hook["id"])
    cfg["repos"].pop(repo, None)
    return [h["id"] for h in matched]


def status(client: GitHubClient, cfg: dict, repo: str | None = None) -> list:
    repos = [repo] if repo else sorted(cfg["repos"])
    channel_by_target = {url + GITHUB_SUFFIX: n for n, url in cfg["channels"].items()}
    rows = []
    for r in repos:
        try:
            discord_hooks = _discord_hooks(client.list_hooks(r))
        except GitHubError as exc:
            rows.append({"repo": r, "error": str(exc)})
            continue
        if not discord_hooks:
            rows.append({"repo": r, "error": "no Discord hook on this repo"})
            continue
        record = cfg["repos"].get(r, {})
        managed_id = _managed_hook_id(cfg, record, discord_hooks)
        for hook in discord_hooks:
            last = hook.get("last_response") or {}
            row = {
                "repo": r,
                "hook_id": hook["id"],
                "active": hook.get("active", False),
                "events": hook.get("events", []),
                "url": hook["config"]["url"],
                "code": last.get("code"),
                "status": last.get("status"),
            }
            if "*" in row["events"] and not _all_events_opt_in(record, hook["id"]):
                managed = hook["id"] == managed_id
                channel = channel_by_target.get(row["url"]) if managed else None
                row["warning"] = all_events_warning(cfg, r, hook["id"], channel)
            rows.append(row)
    return rows


def ping(client: GitHubClient, cfg: dict, repo: str) -> int:
    record = cfg["repos"].get(repo)
    hooks = client.list_hooks(repo)
    matched = []
    if record:
        matched = [h for h in hooks if h["id"] == record.get("hook_id")]
    if not matched:
        matched = _discord_hooks(hooks)
    if not matched:
        raise ConfigError(f"no Discord hook found on {repo}")
    client.ping_hook(repo, matched[0]["id"])
    return matched[0]["id"]
