import json

import pytest

from gh2discord.config import (
    ConfigError,
    load,
    normalize_repo,
    normalize_webhook_url,
    save,
)

VALID = "https://discord.com/api/webhooks/123456/aBc-DeF_123"


@pytest.mark.parametrize(
    "url",
    [
        VALID,
        VALID + "/",
        VALID + "/github",
        VALID + "/github/",
        "https://discordapp.com/api/webhooks/123456/aBc-DeF_123",
        "https://ptb.discord.com/api/webhooks/123456/aBc-DeF_123",
        "https://canary.discord.com/api/webhooks/123456/aBc-DeF_123",
    ],
)
def test_normalize_webhook_accepts_variants(url):
    result = normalize_webhook_url(url)
    assert result.startswith("https://")
    assert not result.endswith("/github")
    assert not result.endswith("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://discord.com/api/webhooks/123/abc",
        "https://example.com/api/webhooks/123/abc",
        "https://discord.com/api/webhooks/abc/def",
        "https://discord.com/api/webhooks/123",
        "not a url",
        "",
    ],
)
def test_normalize_webhook_rejects_invalid(url):
    with pytest.raises(ConfigError):
        normalize_webhook_url(url)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("owner/repo", "owner/repo"),
        ("https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo.git", "owner/repo"),
        ("https://github.com/owner/repo/", "owner/repo"),
        ("github.com/owner/repo", "owner/repo"),
        ("git@github.com:owner/repo.git", "owner/repo"),
        ("owner/repo.name", "owner/repo.name"),
    ],
)
def test_normalize_repo(raw, expected):
    assert normalize_repo(raw) == expected


@pytest.mark.parametrize("raw", ["owner", "owner/repo/extra", "owner repo", "", "a/b c"])
def test_normalize_repo_rejects_invalid(raw):
    with pytest.raises(ConfigError):
        normalize_repo(raw)


def test_load_missing_returns_empty(tmp_path):
    cfg = load(tmp_path / "nope.json")
    assert cfg == {"version": 1, "default_channel": None, "channels": {}, "repos": {}}


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "cfg" / "config.json"
    cfg = {
        "version": 1,
        "default_channel": "general",
        "channels": {"general": VALID},
        "repos": {"o/r": {"channel": "general", "hook_id": 7, "events": ["*"]}},
    }
    save(cfg, path)
    assert load(path) == cfg
    assert not path.with_name(path.name + ".tmp").exists()


def test_load_fills_missing_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"channels": {"x": VALID}}), encoding="utf-8")
    cfg = load(path)
    assert cfg["repos"] == {}
    assert cfg["default_channel"] is None
    assert cfg["channels"] == {"x": VALID}


def test_load_invalid_json_raises(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ConfigError):
        load(path)


def test_load_non_object_raises(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ConfigError):
        load(path)


def test_load_utf8_bom(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes(b'\xef\xbb\xbf{"channels": {}}')
    assert load(path)["channels"] == {}


def test_load_wrong_typed_channels_raises(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"channels": null}', encoding="utf-8")
    with pytest.raises(ConfigError):
        load(path)


def test_load_wrong_typed_repos_raises(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"repos": []}', encoding="utf-8")
    with pytest.raises(ConfigError):
        load(path)


def test_load_wrong_typed_default_raises(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"default_channel": 3}', encoding="utf-8")
    with pytest.raises(ConfigError):
        load(path)


def test_load_utf16_raises_config_error(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes('{"channels": {}}'.encode("utf-16"))
    with pytest.raises(ConfigError):
        load(path)


def test_save_unwritable_raises_config_error(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError):
        save({"version": 1}, blocker / "sub" / "config.json")


def test_normalize_webhook_strips_api_version():
    url = "https://discord.com/api/v10/webhooks/123456/aBc-DeF_123"
    assert normalize_webhook_url(url) == VALID
