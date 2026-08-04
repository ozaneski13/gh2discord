import pytest

from gh2discord import commands
from gh2discord.config import ConfigError

URL_A = "https://discord.com/api/webhooks/111/tokenA"
URL_B = "https://discord.com/api/webhooks/222/tokenB"


class FakeClient:
    def __init__(self, hooks=None):
        self.hooks = hooks or []
        self.created = []
        self.updated = []
        self.deleted = []
        self.pinged = []

    def list_hooks(self, repo):
        return self.hooks

    def create_hook(self, repo, target_url, events):
        hook = {
            "id": 999,
            "active": True,
            "events": events,
            "config": {"url": target_url, "content_type": "json"},
        }
        self.created.append((repo, target_url, events))
        return hook

    def update_hook(self, repo, hook_id, target_url=None, events=None, active=None):
        self.updated.append((repo, hook_id, target_url, events, active))
        url = target_url or next(
            h["config"]["url"] for h in self.hooks if h["id"] == hook_id
        )
        return {
            "id": hook_id,
            "active": True,
            "events": events,
            "config": {"url": url, "content_type": "json"},
        }

    def delete_hook(self, repo, hook_id):
        self.deleted.append((repo, hook_id))

    def ping_hook(self, repo, hook_id):
        self.pinged.append((repo, hook_id))


def base_cfg():
    return {
        "version": 1,
        "default_channel": "general",
        "channels": {"general": URL_A, "alerts": URL_B},
        "repos": {},
    }


def hook(hook_id, url, events=("*",), active=True, content_type="json"):
    return {
        "id": hook_id,
        "active": active,
        "events": list(events),
        "config": {"url": url, "content_type": content_type},
        "last_response": {"code": 204, "status": "active"},
    }


def test_parse_events_all():
    assert commands.parse_events("all") == ["*"]
    assert commands.parse_events("*") == ["*"]


def test_parse_events_list_dedup_sorted():
    assert commands.parse_events("release, push,push") == ["push", "release"]


def test_parse_events_empty_raises():
    with pytest.raises(ConfigError):
        commands.parse_events(" , ")


def test_channel_add_first_becomes_default():
    cfg = {"version": 1, "default_channel": None, "channels": {}, "repos": {}}
    assert commands.channel_add(cfg, "general", URL_A + "/github")
    assert cfg["default_channel"] == "general"
    assert cfg["channels"]["general"] == URL_A


def test_channel_remove_in_use_raises():
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 1, "events": ["*"]}
    with pytest.raises(ConfigError):
        commands.channel_remove(cfg, "general")


def test_channel_remove_reassigns_default():
    cfg = base_cfg()
    commands.channel_remove(cfg, "general")
    assert cfg["default_channel"] == "alerts"


def test_resolve_channel_no_default_raises():
    cfg = base_cfg()
    cfg["default_channel"] = None
    with pytest.raises(ConfigError):
        commands.resolve_channel(cfg)


def test_track_creates_hook():
    client = FakeClient()
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r")
    assert result.action == "created"
    assert client.created == [("o/r", URL_A + "/github", ["*"])]
    assert cfg["repos"]["o/r"] == {"channel": "general", "hook_id": 999, "events": ["*"]}


def test_track_unchanged_when_identical():
    client = FakeClient([hook(1, URL_A + "/github")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r")
    assert result.action == "unchanged"
    assert not client.created
    assert not client.updated


def test_track_updates_events_in_place():
    client = FakeClient([hook(1, URL_A + "/github", events=("push",))])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", events=["*"])
    assert result.action == "updated"
    assert client.updated[0][1] == 1


def test_track_other_discord_hook_without_force_raises():
    client = FakeClient([hook(1, URL_B + "/github")])
    cfg = base_cfg()
    with pytest.raises(ConfigError):
        commands.track(client, cfg, "o/r")


def test_track_force_retargets():
    client = FakeClient([hook(1, URL_B + "/github")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", force=True)
    assert result.action == "retargeted"
    assert client.updated[0][2] == URL_A + "/github"


def test_track_ignores_non_discord_hooks():
    client = FakeClient([hook(1, "https://ci.example.com/webhook")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r")
    assert result.action == "created"


def test_track_channel_override():
    client = FakeClient()
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", channel="alerts")
    assert client.created[0][1] == URL_B + "/github"
    assert result.channel == "alerts"


def test_untrack_by_recorded_id():
    client = FakeClient([hook(7, URL_A + "/github")])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 7, "events": ["*"]}
    deleted = commands.untrack(client, cfg, "o/r")
    assert deleted == [7]
    assert "o/r" not in cfg["repos"]


def test_untrack_falls_back_to_url_match():
    client = FakeClient([hook(9, URL_A + "/github")])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 12345, "events": ["*"]}
    deleted = commands.untrack(client, cfg, "o/r")
    assert deleted == [9]


def test_untrack_nothing_found_returns_empty_and_clears():
    client = FakeClient()
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 1, "events": ["*"]}
    assert commands.untrack(client, cfg, "o/r") == []
    assert "o/r" not in cfg["repos"]


def test_track_form_content_type_is_repaired():
    client = FakeClient([hook(1, URL_A + "/github", content_type="form")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r")
    assert result.action == "updated"
    assert client.updated[0][2] == URL_A + "/github"


def test_track_bare_discord_url_is_conflict():
    client = FakeClient([hook(1, URL_B)])
    cfg = base_cfg()
    with pytest.raises(ConfigError):
        commands.track(client, cfg, "o/r")


def test_track_unchanged_warns_about_extra_discord_hooks():
    client = FakeClient([hook(1, URL_A + "/github"), hook(2, URL_B + "/github")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r")
    assert result.action == "unchanged"
    assert result.warnings
    assert "2" in result.warnings[0]
    assert not client.deleted


def test_track_unchanged_force_deletes_extra_hooks():
    client = FakeClient([hook(1, URL_A + "/github"), hook(2, URL_B + "/github")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", force=True)
    assert result.action == "unchanged"
    assert client.deleted == [("o/r", 2)]


def test_track_force_retargets_first_and_deletes_rest():
    client = FakeClient([hook(1, URL_B + "/github"), hook(2, URL_B)])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", force=True)
    assert result.action == "retargeted"
    assert client.updated[0][1] == 1
    assert client.deleted == [("o/r", 2)]


def test_channel_add_empty_name_raises():
    cfg = base_cfg()
    with pytest.raises(ConfigError):
        commands.channel_add(cfg, "  ", URL_A)


def test_status_reports_delivery():
    client = FakeClient([hook(3, URL_A + "/github")])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 3, "events": ["*"]}
    rows = commands.status(client, cfg)
    assert rows[0]["code"] == 204
    assert rows[0]["hook_id"] == 3


def test_status_no_hook_is_error_row():
    client = FakeClient()
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 3, "events": ["*"]}
    rows = commands.status(client, cfg)
    assert "error" in rows[0]


def test_ping_uses_recorded_hook():
    client = FakeClient([hook(4, URL_A + "/github")])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 4, "events": ["*"]}
    assert commands.ping(client, cfg, "o/r") == 4
    assert client.pinged == [("o/r", 4)]


def test_ping_no_hook_raises():
    client = FakeClient()
    cfg = base_cfg()
    with pytest.raises(ConfigError):
        commands.ping(client, cfg, "o/r")
