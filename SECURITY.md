# Security Policy

## Supported versions

Only the latest release on PyPI receives security fixes.

## Reporting a vulnerability

Please use **GitHub private vulnerability reporting**: go to this repository's
**Security** tab → **Report a vulnerability**. Do not open a public issue for
security problems. You can expect an initial response within 7 days.

## Threat model in one minute

gh2discord is a local CLI with a deliberately small attack surface:

- **Zero runtime dependencies** — Python standard library only. There is no
  third-party code to compromise at install time.
- **One network destination** — the tool talks exclusively to
  `https://api.github.com` over HTTPS, and never follows redirects silently.
- **No secret storage of tokens** — your GitHub token is read from
  `GITHUB_TOKEN`/`GH_TOKEN` or the `gh` CLI at runtime and is never written
  to disk or logged.
- **Local-only webhook registry** — Discord webhook URLs are stored in a
  local config file created with owner-only permissions (0600 on POSIX) and
  are masked (`***`) in all command output.
- **No telemetry** — the tool phones home to no one.

## Release integrity

Every release is built and published by GitHub Actions from this repository
via [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC — no long-lived PyPI tokens exist), with
[PEP 740 digital attestations](https://docs.pypi.org/attestations/) generated
at publish time. You can verify on the
[PyPI project page](https://pypi.org/project/gh2discord/) that each file's
provenance points back to this repository and its `publish.yml` workflow.
All GitHub Actions used in CI are pinned to full commit SHAs.
