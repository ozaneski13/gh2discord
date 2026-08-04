from __future__ import annotations

import http.client
import json
import os
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request

from . import __version__

API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub API error {status}: {message}" if status else message)
        self.status = status
        self.message = message


class AuthError(Exception):
    pass


def resolve_token() -> str:
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        token = os.environ.get(var, "").strip()
        if token:
            return token
    gh = shutil.which("gh")
    if gh:
        try:
            proc = subprocess.run(
                [gh, "auth", "token"], capture_output=True, text=True, timeout=10
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    raise AuthError(
        "no GitHub token found. Set GITHUB_TOKEN (or GH_TOKEN), or log in with the gh CLI.\n"
        "Classic PAT: 'repo' or 'admin:repo_hook' scope. "
        "Fine-grained PAT: Webhooks (write) + Metadata (read)."
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class GitHubClient:
    def __init__(self, token: str, transport=None):
        self._token = token
        self._transport = transport or self._urllib_transport

    def _urllib_transport(self, method: str, url: str, body: bytes | None):
        req = urllib.request.Request(url, method=method, data=body)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", API_VERSION)
        req.add_header("User-Agent", f"gh2discord/{__version__}")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with _OPENER.open(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.read()
            except OSError:
                return exc.code, b""
        except (OSError, http.client.HTTPException) as exc:
            reason = getattr(exc, "reason", exc)
            message = f"network error: {reason}"
            if isinstance(reason, ssl.SSLCertVerificationError):
                message += (
                    " (your Python has no root certificates configured; on macOS run"
                    " 'Install Certificates.command' from your Python folder)"
                )
            raise GitHubError(0, message) from exc

    def request(self, method: str, path: str, payload: dict | None = None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        status, raw = self._transport(method, API_ROOT + path, body)
        data = None
        decode_failed = False
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                decode_failed = True
        if 300 <= status < 400:
            hint = ""
            if isinstance(data, dict) and data.get("url"):
                hint = f" (new API location: {data['url']})"
            raise GitHubError(
                status,
                "repository has moved (renamed or transferred); "
                "re-run with its new owner/repo name" + hint,
            )
        if status >= 400:
            message = ""
            if isinstance(data, dict):
                message = data.get("message", "")
                errors = data.get("errors")
                if errors:
                    message += f" ({json.dumps(errors)})"
            if not message:
                message = raw.decode("utf-8", errors="replace") if raw else "no details"
            if status == 401:
                message += (
                    " -- token invalid or expired; set GITHUB_TOKEN/GH_TOKEN "
                    "or run 'gh auth login'"
                )
            if status == 404:
                message += " -- repo not found, or your token lacks webhook/admin access to it"
            raise GitHubError(status, message)
        if decode_failed:
            raise GitHubError(status, "unexpected non-JSON response from GitHub API")
        return data

    def list_hooks(self, repo: str) -> list:
        hooks, page = [], 1
        while True:
            batch = self.request("GET", f"/repos/{repo}/hooks?per_page=100&page={page}")
            if batch is None:
                batch = []
            if not isinstance(batch, list):
                raise GitHubError(200, "unexpected response shape for hook list")
            hooks.extend(batch)
            if len(batch) < 100:
                return hooks
            page += 1

    def create_hook(self, repo: str, target_url: str, events: list) -> dict:
        payload = {
            "name": "web",
            "active": True,
            "events": events,
            "config": {"url": target_url, "content_type": "json"},
        }
        return self.request("POST", f"/repos/{repo}/hooks", payload)

    def update_hook(
        self,
        repo: str,
        hook_id: int,
        target_url: str | None = None,
        events: list | None = None,
        active: bool | None = None,
    ) -> dict:
        payload: dict = {}
        if target_url is not None:
            payload["config"] = {"url": target_url, "content_type": "json"}
        if events is not None:
            payload["events"] = events
        if active is not None:
            payload["active"] = active
        return self.request("PATCH", f"/repos/{repo}/hooks/{hook_id}", payload)

    def delete_hook(self, repo: str, hook_id: int) -> None:
        self.request("DELETE", f"/repos/{repo}/hooks/{hook_id}")

    def ping_hook(self, repo: str, hook_id: int) -> None:
        self.request("POST", f"/repos/{repo}/hooks/{hook_id}/pings")
