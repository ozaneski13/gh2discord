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


def test_parse_events_default_keyword():
    assert commands.parse_events("default") == list(commands.DEFAULT_EVENTS)
    assert commands.parse_events(" Default ") == list(commands.DEFAULT_EVENTS)


def test_default_events_are_signal_only_and_in_parsed_form():
    defaults = list(commands.DEFAULT_EVENTS)
    assert commands.parse_events(",".join(defaults)) == defaults
    noisy = {"*", "check_run", "check_suite", "workflow_job", "workflow_run", "status"}
    assert not noisy & set(defaults)


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
    defaults = list(commands.DEFAULT_EVENTS)
    assert result.action == "created"
    assert client.created == [("o/r", URL_A + "/github", defaults)]
    assert cfg["repos"]["o/r"] == {"channel": "general", "hook_id": 999, "events": defaults}
    assert not result.warnings


def test_track_explicit_all_creates_wildcard_hook_and_records_opt_in():
    client = FakeClient()
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", events=["*"])
    assert client.created[0][2] == ["*"]
    assert cfg["repos"]["o/r"]["all_events_opt_in"] is True
    assert not result.warnings


def test_track_keeps_existing_wildcard_hook_and_warns():
    client = FakeClient([hook(1, URL_A + "/github")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r")
    assert result.action == "unchanged"
    assert not client.updated
    assert result.events == ["*"]
    assert cfg["repos"]["o/r"] == {"channel": "general", "hook_id": 1, "events": ["*"]}
    assert "sends every GitHub event (*)" in result.warnings[-1]
    assert "gh2discord track o/r --events default" in result.warnings[-1]
    assert "gh2discord track o/r --events all" in result.warnings[-1]


def test_track_keeps_existing_custom_events_silently():
    client = FakeClient([hook(1, URL_A + "/github", events=("release",))])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r")
    assert result.action == "unchanged"
    assert not client.updated
    assert cfg["repos"]["o/r"]["events"] == ["release"]
    assert not result.warnings


def test_track_repair_resends_live_wildcard_events():
    client = FakeClient([hook(1, URL_A + "/github", active=False)])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r")
    assert result.action == "updated"
    assert client.updated == [("o/r", 1, URL_A + "/github", ["*"], True)]
    assert "sends every GitHub event (*)" in result.warnings[-1]


def test_track_events_default_narrows_wildcard_hook():
    client = FakeClient([hook(1, URL_A + "/github")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", events=commands.parse_events("default"))
    assert result.action == "updated"
    assert client.updated[0][3] == list(commands.DEFAULT_EVENTS)
    assert "all_events_opt_in" not in cfg["repos"]["o/r"]
    assert not result.warnings


def test_track_events_all_on_wildcard_hook_records_opt_in_without_writing():
    client = FakeClient([hook(1, URL_A + "/github")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", events=["*"])
    assert result.action == "unchanged"
    assert not client.updated
    assert cfg["repos"]["o/r"]["all_events_opt_in"] is True
    assert not result.warnings


def test_track_opt_in_survives_bare_track_and_explicit_list_clears_it():
    client = FakeClient([hook(1, URL_A + "/github")])
    cfg = base_cfg()
    commands.track(client, cfg, "o/r", events=["*"])
    result = commands.track(client, cfg, "o/r")
    assert not result.warnings
    assert cfg["repos"]["o/r"]["all_events_opt_in"] is True
    commands.track(client, cfg, "o/r", events=["push"])
    assert "all_events_opt_in" not in cfg["repos"]["o/r"]


def test_track_opt_in_for_another_hook_does_not_silence_warning():
    client = FakeClient([hook(2, URL_A + "/github")])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {
        "channel": "general",
        "hook_id": 1,
        "events": ["*"],
        "all_events_opt_in": True,
    }
    result = commands.track(client, cfg, "o/r")
    assert "sends every GitHub event (*)" in result.warnings[-1]
    assert "all_events_opt_in" not in cfg["repos"]["o/r"]


def test_track_explicit_list_containing_star_records_opt_in():
    client = FakeClient([hook(1, URL_A + "/github", events=("push",))])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", events=commands.parse_events("push,*"))
    assert cfg["repos"]["o/r"]["all_events_opt_in"] is True
    assert not result.warnings


def test_all_events_warning_names_non_default_channel():
    client = FakeClient([hook(1, URL_B + "/github")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", channel="alerts")
    assert "gh2discord track o/r --channel alerts --events default" in result.warnings[-1]
    assert "gh2discord track o/r --channel alerts --events all" in result.warnings[-1]


@pytest.mark.parametrize(
    "channel, shown",
    [
        ("geliştirme", "--channel geliştirme "),
        ("my alerts", '--channel "my alerts" '),
        ("50% off", '--channel "50% off" '),
        ("cost$", "--channel 'cost$' "),
        ("ship it!", "--channel 'ship it!' "),
        ("a`b", "--channel 'a`b' "),
        ('say "hi"', "--channel 'say \"hi\"' "),
        ("alerts\\", "--channel 'alerts\\' "),
    ],
)
def test_all_events_warning_quotes_channel_names(channel, shown):
    warning = commands.all_events_warning(base_cfg(), "o/r", 1, channel)
    assert f"gh2discord track o/r {shown}--events default" in warning


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
    assert "ids 2" in result.warnings[0]
    assert not client.deleted


def test_track_unchanged_force_deletes_extra_hooks():
    client = FakeClient([hook(1, URL_A + "/github"), hook(2, URL_B + "/github")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", force=True)
    assert result.action == "unchanged"
    assert client.deleted == [("o/r", 2)]


def test_track_force_retarget_keeps_live_wildcard_events_and_warns():
    client = FakeClient([hook(1, URL_B + "/github")])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", force=True)
    assert client.updated[0][3] == ["*"]
    assert "sends every GitHub event (*)" in result.warnings[-1]


def test_track_force_retarget_keeps_custom_events():
    client = FakeClient([hook(1, URL_B + "/github", events=("release", "push"))])
    cfg = base_cfg()
    result = commands.track(client, cfg, "o/r", force=True)
    assert client.updated[0][3] == ["push", "release"]
    assert not result.warnings


@pytest.mark.parametrize("spec", ["default", "all"])
def test_track_force_retarget_applies_explicit_events(spec):
    client = FakeClient([hook(1, URL_B + "/github")])
    cfg = base_cfg()
    events = commands.parse_events(spec)
    result = commands.track(client, cfg, "o/r", events=events, force=True)
    assert result.action == "retargeted"
    assert client.updated[0][3] == events
    assert not result.warnings
    assert cfg["repos"]["o/r"].get("all_events_opt_in", False) is (spec == "all")


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


def test_status_warns_about_wildcard_hook():
    client = FakeClient([hook(3, URL_A + "/github")])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 3, "events": ["*"]}
    rows = commands.status(client, cfg)
    assert "gh2discord track o/r --events default" in rows[0]["warning"]


def test_status_respects_all_events_opt_in():
    client = FakeClient([hook(3, URL_A + "/github")])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {
        "channel": "general",
        "hook_id": 3,
        "events": ["*"],
        "all_events_opt_in": True,
    }
    rows = commands.status(client, cfg)
    assert "warning" not in rows[0]


def test_status_opt_in_is_tied_to_hook_id():
    client = FakeClient(
        [hook(1, URL_A + "/github"), hook(2, "https://discord.com/api/webhooks/333/tokenC/github")]
    )
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {
        "channel": "general",
        "hook_id": 1,
        "events": ["*"],
        "all_events_opt_in": True,
    }
    rows = commands.status(client, cfg)
    assert "warning" not in rows[0]
    assert "sends every GitHub event (*)" in rows[1]["warning"]


def test_status_stale_opt_in_does_not_silence_recreated_hook():
    client = FakeClient([hook(5, URL_A + "/github")])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {
        "channel": "general",
        "hook_id": 1,
        "events": ["*"],
        "all_events_opt_in": True,
    }
    rows = commands.status(client, cfg)
    assert "gh2discord track o/r --events default" in rows[0]["warning"]


def test_status_without_record_offers_track_commands():
    client = FakeClient([hook(3, URL_B + "/github")])
    rows = commands.status(client, base_cfg(), "o/r")
    assert "gh2discord track o/r --channel alerts --events default" in rows[0]["warning"]


def test_status_extra_wildcard_hook_on_registered_channel_points_to_github():
    client = FakeClient(
        [hook(1, URL_A + "/github", events=("push",)), hook(2, URL_B + "/github")]
    )
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 1, "events": ["push"]}
    rows = commands.status(client, cfg)
    assert "warning" not in rows[0]
    assert "Settings -> Webhooks" in rows[1]["warning"]
    assert "gh2discord track" not in rows[1]["warning"]


def test_status_tracked_hook_on_unregistered_url_points_to_github():
    client = FakeClient([hook(1, "https://discord.com/api/webhooks/333/tokenC/github")])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 1, "events": ["*"]}
    rows = commands.status(client, cfg)
    assert "Settings -> Webhooks" in rows[0]["warning"]
    assert "gh2discord track" not in rows[0]["warning"]


def test_status_uses_the_hook_url_not_the_recorded_channel():
    client = FakeClient([hook(1, URL_B + "/github")])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 1, "events": ["*"]}
    rows = commands.status(client, cfg)
    assert "gh2discord track o/r --channel alerts --events default" in rows[0]["warning"]


def test_status_without_record_offers_commands_only_for_the_default_channel_hook():
    client = FakeClient([hook(1, URL_A + "/github"), hook(2, URL_B + "/github")])
    rows = commands.status(client, base_cfg(), "o/r")
    assert "gh2discord track o/r --events default" in rows[0]["warning"]
    assert "gh2discord track" not in rows[1]["warning"]
    assert "Settings -> Webhooks" in rows[1]["warning"]


def test_status_without_record_and_no_default_channel_hook_points_to_github():
    third = "https://discord.com/api/webhooks/333/tokenC"
    cfg = base_cfg()
    cfg["channels"]["third"] = third
    client = FakeClient([hook(1, URL_B + "/github"), hook(2, third + "/github")])
    rows = commands.status(client, cfg, "o/r")
    assert all("gh2discord track" not in row["warning"] for row in rows)


def test_status_warns_for_mixed_list_with_star_without_opt_in():
    client = FakeClient([hook(1, URL_A + "/github", events=("*", "push"))])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 1, "events": ["*", "push"]}
    assert "warning" in commands.status(client, cfg)[0]


def test_status_default_events_hook_has_no_warning():
    client = FakeClient([hook(3, URL_A + "/github", events=commands.DEFAULT_EVENTS)])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {
        "channel": "general",
        "hook_id": 3,
        "events": list(commands.DEFAULT_EVENTS),
    }
    rows = commands.status(client, cfg)
    assert "warning" not in rows[0]


def test_status_wildcard_hook_on_unregistered_webhook_points_to_github():
    client = FakeClient([hook(3, "https://discord.com/api/webhooks/333/tokenC/github")])
    cfg = base_cfg()
    cfg["repos"]["o/r"] = {"channel": "general", "hook_id": 9, "events": ["*"]}
    rows = commands.status(client, cfg)
    assert "Settings -> Webhooks" in rows[0]["warning"]
    assert "gh2discord track" not in rows[0]["warning"]


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
