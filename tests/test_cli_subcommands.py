import httpx
import pytest
import respx

from canvas_api_mcp.client import CanvasClient
from canvas_api_mcp.config import Config
from canvas_api_mcp.server import _print_config, _run_test

SECRET_TOKEN = "canvas_test_token_do_not_leak_9f8e7d"
CFG = Config(base_url="https://canvas.example.edu", token=SECRET_TOKEN, max_pages=10)


# ---- --config ---------------------------------------------------------


def test_config_prints_base_url_and_max_pages(capsys):
    _print_config(CFG)
    out = capsys.readouterr().out
    assert CFG.base_url in out
    assert str(CFG.max_pages) in out


def test_config_never_leaks_token(capsys):
    _print_config(CFG)
    out = capsys.readouterr().out

    assert SECRET_TOKEN not in out
    assert SECRET_TOKEN[:8] not in out
    assert SECRET_TOKEN[-8:] not in out
    assert f"{len(SECRET_TOKEN)} chars" in out


def test_config_reports_missing_token(capsys):
    empty = Config(base_url="https://canvas.example.edu", token="", max_pages=10)
    _print_config(empty)
    out = capsys.readouterr().out
    assert "not set" in out


# ---- --test -------------------------------------------------------------


@respx.mock
async def test_run_test_success_reports_name_and_course_count(capsys):
    respx.get("https://canvas.example.edu/api/v1/users/self").mock(
        return_value=httpx.Response(200, json={"name": "Ada Lovelace"})
    )
    respx.get("https://canvas.example.edu/api/v1/courses").mock(
        return_value=httpx.Response(200, json=[{"id": 1}, {"id": 2}, {"id": 3}])
    )

    exit_code = await _run_test(CFG)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Ada Lovelace" in out
    assert "3" in out


@respx.mock
async def test_run_test_exits_nonzero_and_surfaces_canvas_error(capsys):
    respx.get("https://canvas.example.edu/api/v1/users/self").mock(
        return_value=httpx.Response(401, json={"errors": [{"message": "Invalid access token"}]})
    )

    exit_code = await _run_test(CFG)
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "access token" in err.lower()
    assert SECRET_TOKEN not in err

@pytest.mark.xfail(reason="waiting on transport-error translation PR to land on main", strict=True)
@respx.mock
async def test_run_test_never_leaks_token_on_transport_failure(capsys):
    respx.get("https://canvas.example.edu/api/v1/users/self").mock(
        side_effect=httpx.ConnectError("nodename nor servname provided, or not known")
    )

    exit_code = await _run_test(CFG)
    output = capsys.readouterr()

    assert exit_code == 1
    assert SECRET_TOKEN not in output.out
    assert SECRET_TOKEN not in output.err