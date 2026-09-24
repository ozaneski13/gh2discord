import io
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import gh2discord.github as gh
from gh2discord import config
from gh2discord.cli import main
from gh2discord.config import config_path, save
from gh2discord.github import AuthError, GitHubClient, resolve_token

URL = "https://discord.com/api/webhooks/111/SecretToken"
EMPTY = {"version": 1, "default_channel": None, "channels": {}, "repos": {}}


@pytest.fixture
def redirect_server():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(301 if self.path == "/start" else 200)
            if self.path == "/start":
                self.send_header("Location", "/elsewhere")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", seen
    server.shutdown()
    server.server_close()


def test_real_transport_never_follows_redirects(redirect_server):
    base, seen = redirect_server
    status, _ = GitHubClient("tok")._urllib_transport("GET", base + "/start", None)
    assert status == 301
    assert seen == ["/start"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_saved_config_is_owner_only(tmp_path):
    path = tmp_path / "config.json"
    save(EMPTY, path)
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_stale_world_readable_tmp_does_not_leak_permissions(tmp_path):
    path = tmp_path / "config.json"
    stale = tmp_path / "config.json.tmp"
    stale.write_text("{}")
    os.chmod(stale, 0o644)
    save(EMPTY, path)
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_overwriting_world_readable_config_tightens_it(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}")
    os.chmod(path, 0o644)
    save(EMPTY, path)
    assert path.stat().st_mode & 0o777 == 0o600


def test_save_leaves_no_tmp_file(tmp_path):
    path = tmp_path / "config.json"
    (tmp_path / "config.json.tmp").write_text("stale")
    save(EMPTY, path)
    assert not (tmp_path / "config.json.tmp").exists()
    assert path.exists()


def test_cli_survives_legacy_console_encoding(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", newline="\n")
    monkeypatch.setattr(sys, "stdout", stream)
    assert main(["channel", "add", "频道", URL]) == 0
    stream.flush()
    assert raw.getvalue().decode("cp1252") == "channel '??' saved (default)\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["track", "o/r", "--channel", URL],
        ["track", URL],
        ["channel", "default", URL],
        ["channel", "remove", URL],
        ["track", "o/r", "--channel", "https://discord.com/api/v10/webhooks/111/SecretToken"],
    ],
)
def test_error_messages_never_print_the_webhook_token(argv, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    assert main(["channel", "add", "general", URL]) == 0
    capsys.readouterr()
    assert main(argv) == 1
    captured = capsys.readouterr()
    assert "SecretToken" not in captured.out + captured.err
    assert "webhooks/111/***" in captured.err


def test_usage_errors_never_print_the_webhook_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    with pytest.raises(SystemExit) as exc:
        main(["channel", "list", URL])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "SecretToken" not in err
    assert "webhooks/111/***" in err


def _gh_only(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(gh.shutil, "which", lambda _: "gh")


def test_env_token_wins_over_gh_cli(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    monkeypatch.setattr(gh.shutil, "which", lambda _: "gh")
    monkeypatch.setattr(gh.subprocess, "run", lambda *a, **k: pytest.fail("gh was called"))
    assert resolve_token() == "from-env"


def test_gh_cli_failure_raises_auth_error(monkeypatch):
    _gh_only(monkeypatch)

    class Proc:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(gh.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(AuthError):
        resolve_token()


def test_gh_cli_timeout_raises_auth_error(monkeypatch):
    _gh_only(monkeypatch)

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired("gh", 10)

    monkeypatch.setattr(gh.subprocess, "run", hang)
    with pytest.raises(AuthError):
        resolve_token()


def test_config_path_windows_uses_appdata(tmp_path, monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config_path() == tmp_path / "gh2discord" / "config.json"


def test_config_path_posix_uses_xdg_config_home(tmp_path, monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_path() == tmp_path / "gh2discord" / "config.json"
