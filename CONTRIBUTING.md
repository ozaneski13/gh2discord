# Contributing & Maintaining

## Dev setup

```bash
git clone https://github.com/ozaneski13/gh2discord
cd gh2discord
pip install -e ".[dev]"
python -m pytest tests/ -q
```

Zero runtime dependencies is a design constraint — new code uses the Python
standard library only. Tests never touch the external network: API-level
tests inject a fake transport into `GitHubClient` (`tests/test_github.py`),
CLI tests replace `cli._client` with a fake client (`tests/test_cli.py`),
and transport-level tests may use a loopback-only server on 127.0.0.1
(`tests/test_security.py`). POSIX-only tests (file modes) are skipped on
Windows and run in the Ubuntu and macOS CI jobs.

## Hash-pinned CI dependencies

CI installs its tools from hash-pinned lock files in `.github/requirements/`:
`test.txt` (pytest) and `build.txt` (build + hatchling, used with
`python -m build --no-isolation` so the build backend is pinned too). After
editing a `.in` file, or to pick up new versions, regenerate both with uv:

```bash
uv pip compile --universal --generate-hashes --python-version 3.9 .github/requirements/test.in -o .github/requirements/test.txt
uv pip compile --universal --generate-hashes --python-version 3.9 .github/requirements/build.in -o .github/requirements/build.txt
```

`--python-version` must match the `requires-python` floor in
`pyproject.toml`; `--universal` resolves every supported Python version and
platform into one file with environment markers.

## Release process

Releases are fully automated via PyPI Trusted Publishing (OIDC) — there is no
PyPI token anywhere, and no manual upload path.

1. Bump the version in **both** places:
   - `pyproject.toml` → `version = "X.Y.Z"`
   - `src/gh2discord/__init__.py` → `__version__ = "X.Y.Z"`
2. Commit and push to `main`; wait for the `tests` workflow to go green.
3. Run the release dry run and wait for it to go green:
   `gh workflow run release-dryrun.yml`, then `gh run watch`. It builds the
   sdist and wheel, round-trips them through the same upload/download-artifact
   pins as `publish.yml`, installs the wheel and runs `gh2discord --version`.
   It never touches PyPI; the PyPI upload step itself only runs in a real
   release.
4. `gh release create vX.Y.Z --title "gh2discord X.Y.Z" --notes "..."`
5. The `publish` workflow builds the sdist/wheel and publishes to PyPI with
   PEP 740 attestations. Verify at https://pypi.org/project/gh2discord/.

## Dependabot / pinned actions

All GitHub Actions are pinned to full commit SHAs; Dependabot proposes weekly
bumps. Rules learned the hard way:

- **`github/codeql-action` refs must be bumped together** (`init`, `analyze`,
  `upload-sarif` — all to the same SHA). Merging only one mixes versions and
  the codeql workflow fails. Dependabot used to propose them as three separate
  PRs; `dependabot.yml` now groups them under `codeql-action`, so they arrive
  as a single PR that is safe to merge as-is. If you ever see them split
  again, bump all three in one commit and close the individual PRs.
- `actions/upload-artifact` and `actions/download-artifact` version
  independently; after bumping either, run the `release-dryrun` workflow. It
  exercises exactly the pair `publish.yml` uses (the PyPI upload step itself
  is only exercised by a real release).
- Dependabot's default limit is 5 open PRs — more bumps may be queued behind
  the visible ones.

## Repo security settings (restore checklist)

If this repo is ever recreated or migrated, re-enable via Settings (or API):
private vulnerability reporting, Dependabot alerts + security updates,
secret scanning push protection, branch protection on `main` (block force
pushes and deletions), and the PyPI trusted publisher binding
(project `gh2discord`, workflow `publish.yml`, environment `pypi`).
