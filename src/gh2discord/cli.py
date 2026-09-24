from __future__ import annotations

import argparse
import re
import sys

from . import __version__, commands
from .config import ConfigError, load, normalize_repo, save
from .github import AuthError, GitHubClient, GitHubError, resolve_token

_TOKEN_RE = re.compile(r"(/api/(?:v\d+/)?webhooks/\d+/)[A-Za-z0-9_-]+")


def _redact(text: str) -> str:
    return _TOKEN_RE.sub(r"\1***", text)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        super().error(_redact(message))


def _mask(url: str) -> str:
    marker = "/api/webhooks/"
    idx = url.find(marker)
    if idx == -1:
        return url
    prefix = url[: idx + len(marker)]
    parts = url[idx + len(marker):].split("/")
    if len(parts) >= 2:
        parts[1] = "***"
    return prefix + "/".join(parts)


def _client() -> GitHubClient:
    return GitHubClient(resolve_token())


def _cmd_channel_add(args) -> int:
    cfg = load()
    is_default = commands.channel_add(cfg, args.name, args.url, args.default)
    save(cfg)
    suffix = " (default)" if is_default else ""
    print(f"channel '{args.name}' saved{suffix}")
    return 0


def _cmd_channel_list(args) -> int:
    cfg = load()
    if not cfg["channels"]:
        print("no channels configured; add one with: gh2discord channel add <name> <url>")
        return 0
    for name in sorted(cfg["channels"]):
        marker = "*" if name == cfg.get("default_channel") else " "
        print(f"{marker} {name}  {_mask(cfg['channels'][name])}")
    return 0


def _cmd_channel_remove(args) -> int:
    cfg = load()
    commands.channel_remove(cfg, args.name)
    save(cfg)
    print(f"channel '{args.name}' removed")
    return 0


def _cmd_channel_default(args) -> int:
    cfg = load()
    commands.channel_default(cfg, args.name)
    save(cfg)
    print(f"default channel is now '{args.name}'")
    return 0


def _cmd_track(args) -> int:
    cfg = load()
    repo = normalize_repo(args.repo)
    events = commands.parse_events(args.events)
    result = commands.track(
        _client(), cfg, repo, channel=args.channel, events=events, force=args.force
    )
    save(cfg)
    print(
        f"{result.action}: {result.repo} -> #{result.channel} "
        f"(hook {result.hook_id}, events: {', '.join(result.events)})"
    )
    for warning in result.warnings:
        print(warning, file=sys.stderr)
    return 0


def _cmd_untrack(args) -> int:
    cfg = load()
    repo = normalize_repo(args.repo)
    deleted = commands.untrack(_client(), cfg, repo)
    save(cfg)
    if not deleted:
        print(
            f"no matching Discord hook found on {repo}; nothing deleted "
            "(local record cleared)",
            file=sys.stderr,
        )
        return 1
    ids = ", ".join(str(i) for i in deleted)
    print(f"untracked {repo} (deleted hook {ids})")
    return 0


def _cmd_list(args) -> int:
    cfg = load()
    if not cfg["repos"]:
        print("no repos tracked; start with: gh2discord track <owner/repo>")
        return 0
    for repo in sorted(cfg["repos"]):
        rec = cfg["repos"][repo]
        events = ", ".join(rec.get("events", ["*"]))
        print(f"{repo}  ->  #{rec.get('channel')}  (events: {events})")
    return 0


def _cmd_status(args) -> int:
    cfg = load()
    repo = normalize_repo(args.repo) if args.repo else None
    if repo is None and not cfg["repos"]:
        print("no repos tracked; start with: gh2discord track <owner/repo>")
        return 0
    rows = commands.status(_client(), cfg, repo)
    failed = False
    for row in rows:
        if "error" in row:
            failed = True
            print(f"{row['repo']}: ERROR - {_redact(row['error'])}")
            continue
        state = "active" if row["active"] else "DISABLED"
        delivery = f"{row['code']} {row['status']}" if row["code"] else "no deliveries yet"
        events = ", ".join(row["events"])
        print(
            f"{row['repo']}: {state}, hook {row['hook_id']} -> {_mask(row['url'])}, "
            f"last delivery: {delivery}, events: {events}"
        )
    return 1 if failed else 0


def _cmd_ping(args) -> int:
    cfg = load()
    repo = normalize_repo(args.repo)
    hook_id = commands.ping(_client(), cfg, repo)
    print(
        f"ping sent to hook {hook_id} on {repo}; verify with 'gh2discord status {repo}' "
        "or the repo's Settings -> Webhooks -> Recent Deliveries on GitHub"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="gh2discord",
        description="Wire GitHub repos to Discord channels with one command.",
    )
    parser.add_argument("--version", action="version", version=f"gh2discord {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    channel = sub.add_parser("channel", help="manage Discord channel webhooks")
    channel_sub = channel.add_subparsers(dest="channel_command", required=True)

    add = channel_sub.add_parser("add", help="register a Discord webhook under a name")
    add.add_argument("name")
    add.add_argument("url", help="Discord webhook URL (with or without /github suffix)")
    add.add_argument("--default", action="store_true", help="make this the default channel")
    add.set_defaults(func=_cmd_channel_add)

    clist = channel_sub.add_parser("list", help="list registered channels")
    clist.set_defaults(func=_cmd_channel_list)

    remove = channel_sub.add_parser("remove", help="remove a registered channel")
    remove.add_argument("name")
    remove.set_defaults(func=_cmd_channel_remove)

    default = channel_sub.add_parser("default", help="set the default channel")
    default.add_argument("name")
    default.set_defaults(func=_cmd_channel_default)

    track = sub.add_parser("track", help="add/refresh the GitHub webhook for a repo")
    track.add_argument("repo", help="owner/repo or GitHub URL")
    track.add_argument("--channel", help="channel name (default: the default channel)")
    track.add_argument(
        "--events",
        default="all",
        help="comma-separated GitHub event list, or 'all' (default: all)",
    )
    track.add_argument(
        "--force",
        action="store_true",
        help="retarget a conflicting Discord hook and delete any other Discord hooks on the repo",
    )
    track.set_defaults(func=_cmd_track)

    untrack = sub.add_parser("untrack", help="delete the repo's Discord webhook")
    untrack.add_argument("repo")
    untrack.set_defaults(func=_cmd_untrack)

    lst = sub.add_parser("list", help="list locally tracked repos")
    lst.set_defaults(func=_cmd_list)

    status = sub.add_parser("status", help="show live hook state and delivery health")
    status.add_argument("repo", nargs="?", help="owner/repo (default: all tracked)")
    status.set_defaults(func=_cmd_status)

    ping = sub.add_parser("ping", help="send a GitHub ping through the hook")
    ping.add_argument("repo")
    ping.set_defaults(func=_cmd_ping)

    return parser


def main(argv: list | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, AuthError, GitHubError) as exc:
        print(f"error: {_redact(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
