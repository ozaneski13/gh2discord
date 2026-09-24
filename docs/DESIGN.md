# gh2discord — Design

**Date:** 2026-08-04
**Status:** Approved (v0.1 scope)

## Goal

One-command setup for GitHub → Discord notifications. Today the flow is manual:
create a Discord channel webhook, copy its URL, open the GitHub repo settings,
add a webhook pointing at `<discord-url>/github`. gh2discord automates the
GitHub side and remembers Discord channels, so tracking a new repo becomes:

```
gh2discord track owner/repo
```

Distributable tool (PyPI), not a personal script. Anyone with a GitHub token
and a Discord webhook can use it against their own repos and servers.

## Non-goals (v0.1)

- Tracking repos the user does not administer (would require polling; out of scope).
- Creating Discord channels/webhooks via bot token (roadmap, phase 2).
- A hosted service or GitHub App. This is a local CLI.

## Mechanism

Discord natively renders GitHub webhook payloads when the GitHub webhook
targets `https://discord.com/api/webhooks/<id>/<token>/github`. No middleware
is needed. The tool only manages GitHub repository webhooks via the REST API.

## CLI surface

```
gh2discord channel add <name> <discord-webhook-url> [--default]
gh2discord channel list
gh2discord channel remove <name>
gh2discord channel default <name>
gh2discord track <owner/repo> [--channel <name>] [--events e1,e2 | --events all] [--force]
gh2discord untrack <owner/repo>
gh2discord list
gh2discord status [<owner/repo>]
gh2discord ping <owner/repo>
gh2discord --version
```

Every `<owner/repo>` argument also accepts a GitHub URL (https or SSH form,
optional `.git` suffix); it is normalized to `owner/repo`.

- `track` is idempotent: if the repo already has a hook pointing at the target
  URL with `content_type: json`, correct events, and active state, nothing is
  written; otherwise the hook is repaired in place (PATCH) instead of creating
  a duplicate. Any *other* hook targeting a Discord webhook (with or without
  the `/github` suffix — a bare Discord URL is always a broken GitHub hook)
  counts as a conflict: the tool warns and aborts unless `--force`, which
  retargets the first conflicting hook and deletes the rest. When the exact
  hook already exists alongside extra Discord hooks, `track` reports them as
  a warning and `--force` deletes them.
- `--events` defaults to `all` (GitHub `*`; Discord silently ignores event
  types it cannot render).
- `untrack` deletes the hook (matched by recorded id, falling back to every
  Discord hook that targets any registered channel, so it can delete more
  than one) and removes the local record. If no matching hook exists on
  GitHub, the local record is still cleared (persisted) and the command
  exits 1.
- `status` reads live hook state incl. `last_response` (delivery health). It
  exits 1 if any repo returns an API error, has no Discord hook, or has an
  unhealthy hook: disabled, or a last delivery outside 2xx. A hook that has
  never delivered counts as healthy.
- `ping` triggers GitHub's webhook ping to verify delivery end to end.

## Auth

Token resolution order: `GITHUB_TOKEN` → `GH_TOKEN` → `gh auth token`
(subprocess, if gh CLI is installed). No token storage by the tool.
Required: classic PAT with `repo` (or `admin:repo_hook`) scope, or
fine-grained PAT with repository **Webhooks: write** + **Metadata: read**.

## Config

JSON at `%APPDATA%\gh2discord\config.json` (Windows) or
`$XDG_CONFIG_HOME/gh2discord/config.json` → `~/.config/gh2discord/config.json`
(POSIX, written with mode 0600 — Discord webhook URLs are secrets).

```json
{
  "version": 1,
  "default_channel": "general",
  "channels": { "general": "https://discord.com/api/webhooks/123/abc" },
  "repos": { "owner/repo": { "channel": "general", "hook_id": 42, "events": ["*"] } }
}
```

Channel URLs are stored canonically **without** the `/github` suffix (accepted
and stripped on input); the suffix is appended when creating GitHub hooks.
The `ptb.`, `canary.` and `discordapp.com` hosts are accepted, and an
`/api/vNN/` version segment is stripped.
GitHub is the source of truth for hook state; `repos` is a local record that
`status`/`untrack` reconcile against live data.

Per-repo channels already work in v0.1: register additional channels with
`channel add`, then `track --channel <name>`. No Discord bot required.

## Modules (SRP)

- `config.py` — load/save/validate config, path resolution. No network.
- `github.py` — token resolution + thin GitHub REST client (urllib), hooks
  CRUD, pagination. No config knowledge.
- `commands.py` — business logic (track/untrack/status/ping/channel ops)
  composing config + github. Returns structured results.
- `cli.py` — argparse, dispatch, human-readable output, exit codes.

Zero runtime dependencies (stdlib only). Python ≥ 3.9. Tests: pytest, never
the external network: a fake transport for API tests, a fake client for CLI
tests, and a loopback-only server for transport-level tests.

## Error UX

- 401 → GitHub's message plus a token hint (set GITHUB_TOKEN/GH_TOKEN or
  `gh auth login`).
- 404 on hooks endpoints → "repo not found **or** token lacks admin/webhook
  access" (GitHub returns 404, not 403, for missing hook permissions).
- 3xx → repository renamed/transferred; redirects are never silently followed.
- 422 → invalid event name(s), echo GitHub's message.
- Console output degrades to `?` instead of crashing on legacy Windows code
  pages (`reconfigure(errors="replace")`).
- Missing token / missing default channel → actionable one-line fix.

Exit codes: 0 ok; 1 API/config error, a repo with no matching Discord hook
(`status`, `untrack`) or an unhealthy hook (`status`); 2 usage error
(argparse default).

## Packaging

`pyproject.toml` (hatchling), console script `gh2discord`, MIT license,
English README. Install: `pipx install gh2discord` / `pip install gh2discord`.

## Roadmap (post-v0.1)

- `--bot` mode: create Discord channel + webhook automatically (bot token,
  Manage Webhooks permission).
- Polling mode for non-admin repos (releases.atom / Events API).
- Org-wide webhook helper for organization accounts.
