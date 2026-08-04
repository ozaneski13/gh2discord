import json

import pytest

import gh2discord.github as gh
from gh2discord.github import AuthError, GitHubClient, GitHubError, resolve_token


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, body):
        self.calls.append((method, url, json.loads(body) if body else None))
        status, payload = self.responses.pop(0)
        raw = json.dumps(payload).encode() if payload is not None else b""
        return status, raw


def make_client(*responses):
    transport = FakeTransport(responses)
    return GitHubClient("tok", transport=transport), transport


def test_request_parses_json():
    client, transport = make_client((200, {"ok": True}))
    assert client.request("GET", "/x") == {"ok": True}
    method, url, body = transport.calls[0]
    assert method == "GET"
    assert url == "https://api.github.com/x"
    assert body is None


def test_request_error_includes_message():
    client, _ = make_client((401, {"message": "Bad credentials"}))
    with pytest.raises(GitHubError) as exc:
        client.request("GET", "/x")
    assert exc.value.status == 401
    assert "Bad credentials" in str(exc.value)


def test_request_404_hints_permissions():
    client, _ = make_client((404, {"message": "Not Found"}))
    with pytest.raises(GitHubError) as exc:
        client.request("GET", "/repos/a/b/hooks")
    assert "webhook/admin access" in str(exc.value)


def test_request_422_includes_errors():
    client, _ = make_client(
        (422, {"message": "Validation Failed", "errors": [{"message": "bad event"}]})
    )
    with pytest.raises(GitHubError) as exc:
        client.request("POST", "/x", {"a": 1})
    assert "bad event" in str(exc.value)


def test_list_hooks_paginates():
    page1 = [{"id": i} for i in range(100)]
    page2 = [{"id": 100}]
    client, transport = make_client((200, page1), (200, page2))
    hooks = client.list_hooks("o/r")
    assert len(hooks) == 101
    assert "page=1" in transport.calls[0][1]
    assert "page=2" in transport.calls[1][1]


def test_create_hook_payload():
    client, transport = make_client((201, {"id": 5}))
    hook = client.create_hook("o/r", "https://discord.com/api/webhooks/1/a/github", ["*"])
    assert hook == {"id": 5}
    _, _, body = transport.calls[0]
    assert body["name"] == "web"
    assert body["active"] is True
    assert body["events"] == ["*"]
    assert body["config"]["content_type"] == "json"


def test_update_hook_partial_payload():
    client, transport = make_client((200, {"id": 5}))
    client.update_hook("o/r", 5, events=["push"])
    _, _, body = transport.calls[0]
    assert body == {"events": ["push"]}


def test_delete_hook_no_body():
    client, transport = make_client((204, None))
    assert client.delete_hook("o/r", 5) is None
    method, url, body = transport.calls[0]
    assert method == "DELETE"
    assert url.endswith("/repos/o/r/hooks/5")
    assert body is None


def test_ping_hook():
    client, transport = make_client((204, None))
    client.ping_hook("o/r", 9)
    method, url, _ = transport.calls[0]
    assert method == "POST"
    assert url.endswith("/repos/o/r/hooks/9/pings")


def test_resolve_token_env_priority(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-github-token")
    monkeypatch.setenv("GH_TOKEN", "from-gh-token")
    assert resolve_token() == "from-github-token"


def test_resolve_token_gh_fallback(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(gh.shutil, "which", lambda _: "/usr/bin/gh")

    class Proc:
        returncode = 0
        stdout = "gh-tok\n"

    monkeypatch.setattr(gh.subprocess, "run", lambda *a, **k: Proc())
    assert resolve_token() == "gh-tok"


def test_resolve_token_missing_raises(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(gh.shutil, "which", lambda _: None)
    with pytest.raises(AuthError):
        resolve_token()


def test_request_3xx_raises_moved():
    client, _ = make_client((301, {"message": "Moved Permanently", "url": "https://api.github.com/repositories/1"}))
    with pytest.raises(GitHubError) as exc:
        client.request("GET", "/repos/old/name/hooks")
    assert exc.value.status == 301
    assert "moved" in str(exc.value)
    assert "repositories/1" in str(exc.value)


def test_request_401_hints_token():
    client, _ = make_client((401, {"message": "Bad credentials"}))
    with pytest.raises(GitHubError) as exc:
        client.request("GET", "/x")
    assert "GITHUB_TOKEN" in str(exc.value)


def test_request_non_json_2xx_raises():
    class T:
        def __call__(self, method, url, body):
            return 200, b"<html>gateway</html>"

    client = GitHubClient("tok", transport=T())
    with pytest.raises(GitHubError):
        client.request("GET", "/x")


def test_list_hooks_non_list_raises():
    client, _ = make_client((200, {"message": "weird"}))
    with pytest.raises(GitHubError):
        client.list_hooks("o/r")
