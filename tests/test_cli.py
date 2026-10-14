import json
import subprocess
import sys

import pytest

import gh2discord.cli as cli
import gh2discord.github as gh
from gh2discord import __version__
from gh2discord.cli import _mask, main
from gh2discord.github import GitHubError

BASE = "https://discord.com/api/webhooks/123456/SecretToken-abc"
URL_A = "https://discord.com/api/webhooks/111/SecretTokenA"
URL_B = "https://discord.com/api/webhooks/222/SecretTokenB"


def test_mask_hides_token():
    assert _mask(BASE) == "https://discord.com/api/webhooks/123456/***"


def test_mask_hides_token_with_github_suffix():
    assert _mask(BASE + "/github") == "https://discord.com/api/webhooks/123456/***/github"


def test_mask_leaves_non_webhook_urls():
    assert _mask("https://example.com/x") == "https://example.com/x"


class FakeClient:
    def __init__(self):
        self.hooks = []
        self.error = None
        self.created = []
        self.deleted = []
        self.pinged = []

    def list_hooks(self, repo):
        if self.error:
            raise self.error
        return self.hooks

    def create_hook(self, repo, target_url, events):
        self.created.append((repo, target_url, events))
        created = {
            "id": 999,
            "active": True,
            "events": events,
            "config": {"url": target_url, "content_type": "json"},
        }
        self.hooks.append(created)
        return created

    def update_hook(self, repo, hook_id, target_url=None, events=None, active=None):
        return {
            "id": hook_id,
            "active": True,
            "events": events,
            "config": {"url": target_url, "content_type": "json"},
        }

    def delete_hook(self, repo, hook_id):
        self.deleted.append((repo, hook_id))

    def ping_hook(self, repo, hook_id):
        self.pinged.append((repo, hook_id))


def hook(hook_id, url):
    return {
        "id": hook_id,
        "active": True,
        "events": ["*"],
        "config": {"url": url, "content_type": "json"},
        "last_response": {"code": 204, "status": "active"},
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    fake = FakeClient()
    monkeypatch.setattr(cli, "_client", lambda: fake)
    return fake


def read_config(tmp_path):
    return json.loads((tmp_path / "gh2discord" / "config.json").read_text(encoding="utf-8"))


def add_channel(name, url):
    assert main(["channel", "add", name, url]) == 0


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"gh2discord {__version__}"


@pytest.mark.parametrize("argv", [[], ["track"], ["channel"], ["channel", "add", "only-name"]])
def test_usage_errors_exit_2(argv):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2


def test_channel_add_first_becomes_default(client, tmp_path, capsys):
    assert main(["channel", "add", "general", URL_A + "/github"]) == 0
    assert "channel 'general' saved (default)" in capsys.readouterr().out
    cfg = read_config(tmp_path)
    assert cfg["channels"]["general"] == URL_A
    assert cfg["default_channel"] == "general"


def test_channel_add_invalid_url_exits_1(client, tmp_path, capsys):
    assert main(["channel", "add", "general", "https://example.com/hook"]) == 1
    assert "error: not a Discord webhook URL" in capsys.readouterr().err
    assert not (tmp_path / "gh2discord" / "config.json").exists()


def test_channel_list_empty(client, capsys):
    assert main(["channel", "list"]) == 0
    assert "no channels configured" in capsys.readouterr().out


def test_channel_list_masks_urls_and_marks_default(client, capsys):
    add_channel("general", URL_A)
    add_channel("alerts", URL_B)
    capsys.readouterr()
    assert main(["channel", "list"]) == 0
    out = capsys.readouterr().out
    assert "* general  https://discord.com/api/webhooks/111/***" in out
    assert "  alerts  https://discord.com/api/webhooks/222/***" in out
    assert "SecretToken" not in out


def test_channel_default_switches(client, tmp_path):
    add_channel("general", URL_A)
    add_channel("alerts", URL_B)
    assert main(["channel", "default", "alerts"]) == 0
    assert read_config(tmp_path)["default_channel"] == "alerts"


def test_channel_default_unknown_exits_1(client, capsys):
    assert main(["channel", "default", "nope"]) == 1
    assert "error: unknown channel 'nope'" in capsys.readouterr().err


def test_channel_remove_refused_while_in_use(client, tmp_path, capsys):
    add_channel("general", URL_A)
    assert main(["track", "o/r"]) == 0
    capsys.readouterr()
    assert main(["channel", "remove", "general"]) == 1
    assert "still used by: o/r" in capsys.readouterr().err
    assert "general" in read_config(tmp_path)["channels"]


def test_channel_remove_unused(client, tmp_path):
    add_channel("general", URL_A)
    add_channel("alerts", URL_B)
    assert main(["channel", "remove", "alerts"]) == 0
    assert "alerts" not in read_config(tmp_path)["channels"]


def test_track_creates_hook_and_records_it(client, tmp_path, capsys):
    add_channel("general", URL_A)
    capsys.readouterr()
    assert main(["track", "o/r"]) == 0
    captured = capsys.readouterr()
    assert (
        "created: o/r -> #general (hook 999, events: issue_comment, issues, "
        "pull_request, pull_request_review, push, release)"
    ) in captured.out
    assert captured.err == ""
    defaults = [
        "issue_comment",
        "issues",
        "pull_request",
        "pull_request_review",
        "push",
        "release",
    ]
    assert client.created == [("o/r", URL_A + "/github", defaults)]
    assert read_config(tmp_path)["repos"]["o/r"] == {
        "channel": "general",
        "hook_id": 999,
        "events": defaults,
    }


def test_track_events_all_is_an_explicit_opt_in(client, tmp_path, capsys):
    add_channel("general", URL_A)
    capsys.readouterr()
    assert main(["track", "o/r", "--events", "all"]) == 0
    captured = capsys.readouterr()
    assert "created: o/r -> #general (hook 999, events: *)" in captured.out
    assert captured.err == ""
    assert read_config(tmp_path)["repos"]["o/r"]["all_events_opt_in"] is True


def test_track_keeps_existing_wildcard_hook_and_warns(client, tmp_path, capsys):
    add_channel("general", URL_A)
    client.hooks.append(hook(1, URL_A + "/github"))
    capsys.readouterr()
    assert main(["track", "o/r"]) == 0
    captured = capsys.readouterr()
    assert "unchanged: o/r -> #general (hook 1, events: *)" in captured.out
    assert "gh2discord track o/r --events default" in captured.err
    assert "SecretToken" not in captured.err
    assert read_config(tmp_path)["repos"]["o/r"]["events"] == ["*"]


def test_track_empty_events_exits_1(client, capsys):
    add_channel("general", URL_A)
    assert main(["track", "o/r", "--events", " , "]) == 1
    assert "no events given" in capsys.readouterr().err
    assert client.created == []


def test_track_help_documents_default_events(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["track", "--help"])
    assert exc.value.code == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "issue_comment, issues, pull_request, pull_request_review, push, release" in out
    assert "an existing hook keeps its events" in out


@pytest.mark.parametrize(
    "ref", ["https://github.com/o/r", "https://github.com/o/r.git", "git@github.com:o/r.git"]
)
def test_track_accepts_github_urls(client, tmp_path, ref):
    add_channel("general", URL_A)
    assert main(["track", ref]) == 0
    assert list(read_config(tmp_path)["repos"]) == ["o/r"]


def test_track_explicit_events_are_sorted(client):
    add_channel("general", URL_A)
    assert main(["track", "o/r", "--events", "release,push"]) == 0
    assert client.created[0][2] == ["push", "release"]


def test_track_without_channel_exits_1(client, capsys):
    assert main(["track", "o/r"]) == 1
    assert "no default channel configured" in capsys.readouterr().err
    assert client.created == []


def test_track_conflict_without_force_changes_nothing(client, tmp_path, capsys):
    add_channel("general", URL_A)
    client.hooks.append(hook(7, URL_B + "/github"))
    capsys.readouterr()
    assert main(["track", "o/r"]) == 1
    assert "--force" in capsys.readouterr().err
    assert client.created == []
    assert client.deleted == []
    assert read_config(tmp_path)["repos"] == {}


def test_track_warns_about_extra_hooks(client, capsys):
    add_channel("general", URL_A)
    client.hooks.extend([hook(1, URL_A + "/github"), hook(2, URL_B + "/github")])
    capsys.readouterr()
    assert main(["track", "o/r"]) == 0
    assert "re-run with --force to delete them" in capsys.readouterr().err
    assert client.deleted == []


def test_track_force_deletes_extra_hooks(client, capsys):
    add_channel("general", URL_A)
    client.hooks.extend([hook(1, URL_A + "/github"), hook(2, URL_B + "/github")])
    capsys.readouterr()
    assert main(["track", "o/r", "--force"]) == 0
    captured = capsys.readouterr()
    assert "unchanged: o/r" in captured.out
    assert "deleted 1 other Discord hook(s): 2" in captured.err
    assert client.deleted == [("o/r", 2)]


def test_untrack_deletes_hook(client, tmp_path, capsys):
    add_channel("general", URL_A)
    main(["track", "o/r"])
    capsys.readouterr()
    assert main(["untrack", "o/r"]) == 0
    assert "untracked o/r (deleted hook 999)" in capsys.readouterr().out
    assert read_config(tmp_path)["repos"] == {}


def test_untrack_without_hook_clears_record_and_exits_1(client, tmp_path, capsys):
    add_channel("general", URL_A)
    main(["track", "o/r"])
    client.hooks.clear()
    capsys.readouterr()
    assert main(["untrack", "o/r"]) == 1
    assert "nothing deleted (local record cleared)" in capsys.readouterr().err
    assert read_config(tmp_path)["repos"] == {}


def test_list_empty_then_populated(client, capsys):
    assert main(["list"]) == 0
    assert "no repos tracked" in capsys.readouterr().out
    add_channel("general", URL_A)
    main(["track", "o/r", "--events", "push"])
    capsys.readouterr()
    assert main(["list"]) == 0
    assert "o/r  ->  #general  (events: push)" in capsys.readouterr().out


def test_status_nothing_tracked(client, capsys):
    assert main(["status"]) == 0
    assert "no repos tracked" in capsys.readouterr().out


def test_status_healthy_hook_is_masked(client, capsys):
    add_channel("general", URL_A)
    main(["track", "o/r"])
    client.hooks[0]["last_response"] = {"code": 204, "status": "active"}
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "o/r: active, hook 999 -> https://discord.com/api/webhooks/111/***/github" in out
    assert "last delivery: 204 active" in out
    assert "SecretToken" not in out


def test_status_disabled_hook_exits_1(client, capsys):
    add_channel("general", URL_A)
    main(["track", "o/r"])
    client.hooks[0]["active"] = False
    capsys.readouterr()
    assert main(["status"]) == 1
    assert "o/r: DISABLED" in capsys.readouterr().out


def test_status_failing_delivery_exits_1(client, capsys):
    add_channel("general", URL_A)
    main(["track", "o/r"])
    client.hooks[0]["last_response"] = {"code": 404, "status": "invalid"}
    capsys.readouterr()
    assert main(["status"]) == 1
    assert "last delivery: 404 invalid" in capsys.readouterr().out


def test_status_hook_without_deliveries_is_healthy(client, capsys):
    add_channel("general", URL_A)
    main(["track", "o/r"])
    capsys.readouterr()
    assert main(["status"]) == 0
    assert "last delivery: no deliveries yet" in capsys.readouterr().out


def test_status_warns_about_wildcard_hook_without_failing(client, capsys):
    add_channel("general", URL_A)
    client.hooks.append(hook(1, URL_A + "/github"))
    capsys.readouterr()
    assert main(["status", "o/r"]) == 0
    captured = capsys.readouterr()
    assert "o/r: active, hook 1" in captured.out
    assert "sends every GitHub event (*)" in captured.err
    assert "gh2discord track o/r --events default" in captured.err


def test_status_rate_limited_wildcard_hook_exits_1(client, capsys):
    add_channel("general", URL_A)
    client.hooks.append(hook(1, URL_A + "/github"))
    client.hooks[0]["last_response"] = {"code": 429, "status": "failed"}
    capsys.readouterr()
    assert main(["status", "o/r"]) == 1
    captured = capsys.readouterr()
    assert "last delivery: 429 failed" in captured.out
    assert "HTTP 429" in captured.err


def test_status_repo_without_hook_exits_1(client, capsys):
    assert main(["status", "o/none"]) == 1
    assert "o/none: ERROR - no Discord hook on this repo" in capsys.readouterr().out


def test_status_api_error_exits_1(client, capsys):
    client.error = GitHubError(404, "Not Found")
    assert main(["status", "o/r"]) == 1
    assert "o/r: ERROR - GitHub API error 404" in capsys.readouterr().out


def test_ping_uses_recorded_hook(client, capsys):
    add_channel("general", URL_A)
    main(["track", "o/r"])
    capsys.readouterr()
    assert main(["ping", "o/r"]) == 0
    assert "ping sent to hook 999 on o/r" in capsys.readouterr().out
    assert client.pinged == [("o/r", 999)]


def test_ping_without_hook_exits_1(client, capsys):
    assert main(["ping", "o/r"]) == 1
    assert "error: no Discord hook found on o/r" in capsys.readouterr().err


def test_missing_token_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(gh.shutil, "which", lambda _: None)
    add_channel("general", URL_A)
    capsys.readouterr()
    assert main(["track", "o/r"]) == 1
    assert "error: no GitHub token found" in capsys.readouterr().err


def test_module_entry_point():
    proc = subprocess.run(
        [sys.executable, "-m", "gh2discord", "--version"], capture_output=True, text=True
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"gh2discord {__version__}"
