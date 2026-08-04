from gh2discord.cli import _mask

BASE = "https://discord.com/api/webhooks/123456/SecretToken-abc"


def test_mask_hides_token():
    assert _mask(BASE) == "https://discord.com/api/webhooks/123456/***"


def test_mask_hides_token_with_github_suffix():
    assert _mask(BASE + "/github") == "https://discord.com/api/webhooks/123456/***/github"


def test_mask_leaves_non_webhook_urls():
    assert _mask("https://example.com/x") == "https://example.com/x"
