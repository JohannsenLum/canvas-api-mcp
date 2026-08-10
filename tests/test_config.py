import pytest
from canvas_api_mcp.config import Config, ConfigError


def test_from_env_reads_required_values():
    cfg = Config.from_env({
        "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
        "CANVAS_TOKEN": "abc123",
    })
    assert cfg.base_url == "https://canvas.nus.edu.sg"
    assert cfg.token == "abc123"
    assert cfg.max_pages == 10


def test_strips_trailing_slash_and_api_suffix():
    cfg = Config.from_env({
        "CANVAS_BASE_URL": "https://canvas.nus.edu.sg/api/v1/",
        "CANVAS_TOKEN": "abc123",
    })
    assert cfg.base_url == "https://canvas.nus.edu.sg"


def test_missing_token_raises_actionable_error():
    with pytest.raises(ConfigError) as exc:
        Config.from_env({"CANVAS_BASE_URL": "https://canvas.nus.edu.sg"})
    assert "CANVAS_TOKEN" in str(exc.value)
    assert "profile/settings" in str(exc.value)


def test_missing_base_url_raises():
    with pytest.raises(ConfigError) as exc:
        Config.from_env({"CANVAS_TOKEN": "abc123"})
    assert "CANVAS_BASE_URL" in str(exc.value)


def test_rejects_non_https_base_url():
    with pytest.raises(ConfigError) as exc:
        Config.from_env({"CANVAS_BASE_URL": "http://canvas.nus.edu.sg", "CANVAS_TOKEN": "x"})
    assert "https" in str(exc.value).lower()


def test_max_pages_override():
    cfg = Config.from_env({
        "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
        "CANVAS_TOKEN": "abc123",
        "CANVAS_MAX_PAGES": "3",
    })
    assert cfg.max_pages == 3


def test_timeout_default():
    cfg = Config.from_env({
        "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
        "CANVAS_TOKEN": "abc123",
    })
    assert cfg.timeout == 30.0


def test_timeout_override():
    cfg = Config.from_env({
        "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
        "CANVAS_TOKEN": "abc123",
        "CANVAS_TIMEOUT": "120",
    })
    assert cfg.timeout == 120.0


def test_timeout_fractional():
    cfg = Config.from_env({
        "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
        "CANVAS_TOKEN": "abc123",
        "CANVAS_TIMEOUT": "2.5",
    })
    assert cfg.timeout == 2.5


def test_timeout_must_be_positive():
    with pytest.raises(ConfigError) as exc:
        Config.from_env({
            "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
            "CANVAS_TOKEN": "abc123",
            "CANVAS_TIMEOUT": "0",
        })
    assert "CANVAS_TIMEOUT" in str(exc.value)


def test_timeout_must_be_numeric():
    with pytest.raises(ConfigError) as exc:
        Config.from_env({
            "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
            "CANVAS_TOKEN": "abc123",
            "CANVAS_TIMEOUT": "fast",
        })
    assert "CANVAS_TIMEOUT" in str(exc.value)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "Infinity"])
def test_timeout_rejects_non_finite(value):
    """float() accepts these, and NaN compares False against everything.

    A plain `timeout <= 0` check lets "nan" and "inf" straight through, and an
    infinite timeout means the client waits forever on a hung Canvas instead of
    giving up, which is precisely what the person setting a timeout wanted to
    avoid. Silent, and only visible when something is already going wrong.
    """
    with pytest.raises(ConfigError) as exc:
        Config.from_env({
            "CANVAS_BASE_URL": "https://canvas.nus.edu.sg",
            "CANVAS_TOKEN": "abc123",
            "CANVAS_TIMEOUT": value,
        })
    assert "CANVAS_TIMEOUT" in str(exc.value)
