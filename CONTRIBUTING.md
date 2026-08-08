# Contributing & Maintaining

## Dev setup

```bash
git clone https://github.com/ozaneski13/gh2discord
cd gh2discord
pip install -e ".[dev]"
python -m pytest tests/ -q
```

Zero runtime dependencies is a design constraint — new code uses the Python
standard library only. Unit tests must not touch the network: inject a fake
transport into `GitHubClient` (see `tests/test_github.py`).

## Release process

Releases are fully automated via PyPI Trusted Publishing (OIDC) — there is no
PyPI token anywhere, and no manual upload path.

1. Bump the version in **both** places:
   - `pyproject.toml` → `version = "X.Y.Z"`
   - `src/gh2discord/__init__.py` → `__version__ = "X.Y.Z"`
2. Commit and push to `main`; wait for the `tests` workflow to go green.
3. `gh release create vX.Y.Z --title "gh2discord X.Y.Z" --notes "..."`
4. The `publish` workflow builds the sdist/wheel and publishes to PyPI with
   PEP 740 attestations. Verify at https://pypi.org/project/gh2discord/.

## Dependabot / pinned actions

All GitHub Actions are pinned to full commit SHAs; Dependabot proposes weekly
bumps. Rules learned the hard way:

- **`github/codeql-action` refs must be bumped together** (`init`, `analyze`,
  `upload-sarif` — all to the same SHA). Dependabot proposes them as separate
  PRs; merging only one mixes major versions and the codeql workflow fails.
- `actions/upload-artifact` and `actions/download-artifact` version
  independently; after bumping either, the pair is only exercised for real by
  the next release run (the `publish` workflow), so watch that run.
- Dependabot's default limit is 5 open PRs — more bumps may be queued behind
  the visible ones.

## Repo security settings (restore checklist)

If this repo is ever recreated or migrated, re-enable via Settings (or API):
private vulnerability reporting, Dependabot alerts + security updates,
secret scanning push protection, branch protection on `main` (block force
pushes and deletions), and the PyPI trusted publisher binding
(project `gh2discord`, workflow `publish.yml`, environment `pypi`).
