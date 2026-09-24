# gh2discord

[![PyPI](https://img.shields.io/pypi/v/gh2discord)](https://pypi.org/project/gh2discord/)
[![tests](https://github.com/ozaneski13/gh2discord/actions/workflows/test.yml/badge.svg)](https://github.com/ozaneski13/gh2discord/actions/workflows/test.yml)
[![CodeQL](https://github.com/ozaneski13/gh2discord/actions/workflows/codeql.yml/badge.svg)](https://github.com/ozaneski13/gh2discord/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/ozaneski13/gh2discord/badge)](https://scorecard.dev/viewer/?uri=github.com/ozaneski13/gh2discord)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fozaneski13%2Fgh2discord%2Fmain%2Fpyproject.toml)](https://pypi.org/project/gh2discord/)

Wire GitHub repos to Discord channels with one command.

Discord can render GitHub webhook payloads natively — no bot, no middleware.
The only friction is the manual setup: create a Discord webhook, copy the URL,
open every repo's settings, paste the URL with a magic `/github` suffix.
**gh2discord** automates the GitHub side and remembers your Discord channels,
so tracking a new repo becomes:

```bash
gh2discord track owner/repo
```

## Install

```bash
pipx install gh2discord   # recommended
# or
pip install gh2discord
```

Zero runtime dependencies. Python 3.9+.

## Setup (once)

1. In Discord: **Channel settings → Integrations → Webhooks → New Webhook**,
   copy the webhook URL.
2. Register it:

```bash
gh2discord channel add general https://discord.com/api/webhooks/<id>/<token> --default
```

3. Authenticate with GitHub — any one of:
   - `gh` CLI already logged in (nothing to do; the token is picked up automatically), or
   - `GITHUB_TOKEN` / `GH_TOKEN` environment variable.
     - Classic PAT: `repo` or `admin:repo_hook` scope.
     - Fine-grained PAT: **Webhooks (write)** + **Metadata (read)** on the repos you track.

   If both are present, `GITHUB_TOKEN` / `GH_TOKEN` take precedence over the
   `gh` CLI login, so a stale variable wins over a working `gh` session.

You can only track repos you administer — GitHub allows webhook management
for repo admins only.

## Usage

```bash
gh2discord track owner/repo                     # default channel, all events
gh2discord track owner/repo --events push,release,issues,pull_request
gh2discord track owner/repo --channel alerts    # per-repo channel
gh2discord list                                 # tracked repos
gh2discord status                               # live hook health; exits 1 if any hook is unhealthy
gh2discord status owner/repo                    # one repo only
gh2discord ping owner/repo                      # end-to-end delivery test
gh2discord untrack owner/repo                   # remove the hook
gh2discord --version
```

Repo arguments also accept GitHub URLs (`https://github.com/owner/repo`,
`git@github.com:owner/repo.git`).

`track` is idempotent: run it twice and you get one hook, not two. It also
repairs broken hooks in place (wrong content type, disabled, or stale events).
If the repo already posts to a *different* Discord webhook, `track` stops with
an error and changes nothing; `--force` retargets that hook and deletes any
other Discord hooks. If the correct hook exists alongside extra Discord hooks,
`track` warns, and `--force` deletes the extras.

Multiple channels work without any bot: register each channel's webhook once
(`channel add`), then route repos with `--channel`.

```bash
gh2discord channel add releases https://discord.com/api/webhooks/<id>/<token>
gh2discord track owner/lib --channel releases --events release
gh2discord channel list                # registered channels (URLs masked, * = default)
gh2discord channel default releases    # change the default channel
gh2discord channel remove releases     # refused while a tracked repo still uses it
```

## Notes

- Config lives at `%APPDATA%\gh2discord\config.json` (Windows) or
  `$XDG_CONFIG_HOME/gh2discord/config.json` (Linux/macOS; defaults to
  `~/.config/gh2discord/config.json`). Discord webhook URLs are
  secrets — the file is written with owner-only permissions on POSIX; don't
  commit it anywhere.
- `--events all` (the default) sends everything GitHub emits; Discord silently
  ignores event types it can't render. Use an explicit list for quieter channels.
- GitHub returns 404 (not 403) when your token lacks webhook access to a repo —
  if a repo you own reports "not found", check your token scopes first.

## Security

This tool is built to be easy to audit and hard to abuse:

- **Zero runtime dependencies** — pure Python standard library; the whole
  source is six small files (about 700 lines).
- **Single network destination** — only `https://api.github.com`, over HTTPS,
  with silent redirects disabled.
- **Your token never leaves your machine** — read from the environment or the
  `gh` CLI at runtime, never stored, never logged.
- **Webhook URLs are treated as secrets** — stored locally with owner-only
  file permissions and masked (`***`) in every command output.
- **No telemetry, no analytics, no phone-home.**
- **Verifiable releases** — published to PyPI exclusively by GitHub Actions
  via [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) with
  [PEP 740 attestations](https://docs.pypi.org/attestations/); check the
  provenance on the [PyPI page](https://pypi.org/project/gh2discord/). No
  human ever uploads a build by hand, and no long-lived PyPI token exists.
- **Hardened CI** — all Actions pinned to full commit SHAs, CodeQL scanning,
  OpenSSF Scorecard, Dependabot updates, secret-scanning push protection,
  and a protected `main` branch (no force pushes, no deletion).

Found a vulnerability? See [SECURITY.md](https://github.com/ozaneski13/gh2discord/blob/main/SECURITY.md) — please use private
reporting, not a public issue.

## Roadmap

- `--bot` mode: create the Discord channel + webhook automatically (bot token).
- Polling mode for repos you don't administer (releases/commits feeds).
- Org-wide webhook helper for organization accounts.

## License & Attribution

MIT © [Ozan Eski](https://github.com/ozaneski13) — free for everyone and every
use, personal or commercial. The one requirement (per the MIT license terms):
if you copy, modify, or redistribute this code or a substantial portion of it,
you must keep the copyright notice — credit **Ozan Eski / gh2discord** and
link back to this repository.
