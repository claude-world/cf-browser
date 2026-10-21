"""Smoke tests for the MCP server — verify tools are registered correctly.

Note: These tests access FastMCP internals (_tool_manager._tools) which
may break on FastMCP version upgrades. If tests fail after an MCP library
update, check for changes to the internal registry API.
"""

import json
import stat
from pathlib import Path

import pytest

from cf_browser.exceptions import (
    BrowserUnavailableError,
    CrawlJobError,
    NotFoundError,
    TransportError,
)
import cf_browser_mcp.server as server_module

from cf_browser_mcp.server import mcp


def test_server_has_expected_tool_count():
    """The MCP server should expose exactly 17 browser tools."""
    tools = mcp._tool_manager._tools  # FastMCP internal registry
    assert len(tools) == 17


def test_all_tool_names_present():
    """Every tool name should match a browser_* convention."""
    tools = mcp._tool_manager._tools
    expected = {
        # Read-only tools
        "browser_content",
        "browser_screenshot",
        "browser_pdf",
        "browser_markdown",
        "browser_snapshot",
        "browser_scrape",
        "browser_json",
        "browser_links",
        "browser_crawl",
        "browser_crawl_status",
        "browser_delete_crawl",
        "browser_a11y",
        # Interaction tools
        "browser_click",
        "browser_type",
        "browser_evaluate",
        "browser_interact",
        "browser_submit_form",
    }
    assert set(tools.keys()) == expected


def test_get_client_rejects_ambiguous_credentials(monkeypatch):
    server_module._client = None
    monkeypatch.delenv("CF_BROWSER_MODE", raising=False)
    monkeypatch.setenv("CF_ACCOUNT_ID", "account")
    monkeypatch.setenv("CF_API_TOKEN", "token")
    monkeypatch.setenv("CF_BROWSER_URL", "https://worker.example")
    monkeypatch.setenv("CF_BROWSER_API_KEY", "key")

    with pytest.raises(RuntimeError, match="CF_BROWSER_MODE"):
        server_module.get_client()


def test_build_kwargs_validates_and_preserves_authentication_controls():
    kwargs = server_module._build_kwargs(
        authenticate={"username": "user", "password": "pass"},
        add_script_tag=[{"content": "window.ready = true"}],
        add_style_tag='[{"url":"https://example.com/style.css"}]',
        reject_resource_types=["image"],
        wait_until="networkidle0",
        timeout=5_000,
    )
    assert kwargs == {
        "authenticate": {"username": "user", "password": "pass"},
        "add_script_tag": [{"content": "window.ready = true"}],
        "add_style_tag": [{"url": "https://example.com/style.css"}],
        "reject_resource_types": ["image"],
        "wait_until": "networkidle0",
        "timeout": 5_000,
    }

    with pytest.raises(ValueError, match="username and password"):
        server_module._build_kwargs(authenticate={"username": "user"})
    with pytest.raises(ValueError, match="content or url"):
        server_module._build_kwargs(add_script_tag=[{}])


@pytest.mark.asyncio
async def test_browser_interact_accepts_structured_actions(monkeypatch):
    captured = None

    class Client:
        async def interact(self, _url, actions, **_kwargs):
            nonlocal captured
            captured = actions
            return {"results": []}

    monkeypatch.setattr(server_module, "get_client", lambda: Client())
    actions = [{"action": "click", "selector": "button"}]
    await server_module.browser_interact("https://example.com", actions)
    assert captured == actions


@pytest.mark.asyncio
async def test_browser_submit_form_accepts_structured_fields(monkeypatch):
    captured = None

    class Client:
        async def submit_form(self, _url, fields, **_kwargs):
            nonlocal captured
            captured = fields
            return {"url": "https://example.com/done"}

    monkeypatch.setattr(server_module, "get_client", lambda: Client())
    fields = {"#email": "user@example.com"}
    await server_module.browser_submit_form("https://example.com", fields)
    assert captured == fields


@pytest.mark.asyncio
async def test_browser_crawl_defaults_to_rendered_current_contract(monkeypatch):
    captured = None

    class Client:
        async def crawl(self, _url, **kwargs):
            nonlocal captured
            captured = kwargs
            return "job-id"

    monkeypatch.setattr(server_module, "get_client", lambda: Client())
    await server_module.browser_crawl("https://example.com")
    assert captured == {
        "limit": 10,
        "render": True,
        "source": "all",
        "options": {
            "includeExternalLinks": False,
            "includeSubdomains": False,
        },
    }


@pytest.mark.asyncio
async def test_browser_crawl_exposes_rendered_browser_options(monkeypatch):
    captured = None

    class Client:
        async def crawl(self, _url, **kwargs):
            nonlocal captured
            captured = kwargs
            return "job-id"

    monkeypatch.setattr(server_module, "get_client", lambda: Client())
    await server_module.browser_crawl(
        "https://example.com",
        authenticate={"username": "user", "password": "pass"},
        wait_for="main",
        add_script_tag=[{"content": "window.ready = true"}],
    )
    assert captured["authenticate"] == {"username": "user", "password": "pass"}
    assert captured["wait_for"] == "main"
    assert captured["add_script_tag"] == [{"content": "window.ready = true"}]

    with pytest.raises(ValueError, match="render=True"):
        await server_module.browser_crawl(
            "https://example.com",
            render=False,
            authenticate={"username": "user", "password": "pass"},
        )


@pytest.mark.asyncio
async def test_browser_crawl_exposes_current_crawl_contract(monkeypatch):
    captured = None

    class Client:
        async def crawl(self, _url, **kwargs):
            nonlocal captured
            captured = kwargs
            return "job-id"

    monkeypatch.setattr(server_module, "get_client", lambda: Client())
    await server_module.browser_crawl(
        "https://example.com/docs/",
        depth=3,
        formats=["markdown", "json"],
        crawl_purposes=["search"],
        max_age=3600,
        modified_since=1_780_000_000,
        include_patterns=["**/docs/**"],
        exclude_patterns='["**/private/**"]',
        json_options={"prompt": "Extract the title"},
        reject_request_patterns=["*.png"],
        javascript_enabled=False,
    )
    assert captured["depth"] == 3
    assert captured["formats"] == ["markdown", "json"]
    assert captured["crawl_purposes"] == ["search"]
    assert captured["max_age"] == 3600
    assert captured["modified_since"] == 1_780_000_000
    assert captured["include_patterns"] == ["**/docs/**"]
    assert captured["exclude_patterns"] == ["**/private/**"]
    assert captured["json_options"] == {"prompt": "Extract the title"}
    assert captured["reject_request_patterns"] == ["*.png"]
    assert captured["javascript_enabled"] is False


@pytest.mark.asyncio
async def test_browser_crawl_exposes_structured_rendered_options_and_cache_ttl(monkeypatch):
    captured = None

    class Client:
        async def crawl(self, _url, **kwargs):
            nonlocal captured
            captured = kwargs
            return "job-id"

    monkeypatch.setattr(server_module, "get_client", lambda: Client())
    await server_module.browser_crawl(
        "https://example.com",
        cache_ttl=3_600,
        goto_options={
            "waitUntil": ["load", "networkidle2"],
            "referer": "https://referrer.example/",
        },
        wait_for_selector='{"selector":"main","visible":true,"timeout":90000}',
        viewport={
            "width": 1_280,
            "height": 720,
            "deviceScaleFactor": 2,
            "isMobile": False,
        },
    )
    assert captured["cache_ttl"] == 3_600
    assert captured["gotoOptions"] == {
        "waitUntil": ["load", "networkidle2"],
        "referer": "https://referrer.example/",
    }
    assert captured["waitForSelector"] == {
        "selector": "main",
        "visible": True,
        "timeout": 90_000,
    }
    assert captured["viewport"] == {
        "width": 1_280,
        "height": 720,
        "deviceScaleFactor": 2,
        "isMobile": False,
    }


@pytest.mark.asyncio
async def test_browser_crawl_maps_no_cache_and_rejects_nested_alias_conflicts(monkeypatch):
    captured = None

    class Client:
        async def crawl(self, _url, **kwargs):
            nonlocal captured
            captured = kwargs
            return "job-id"

    monkeypatch.setattr(server_module, "get_client", lambda: Client())
    await server_module.browser_crawl("https://example.com", no_cache=True)
    assert captured["no_cache"] is True
    assert captured["cache_ttl"] == 0

    with pytest.raises(ValueError, match="non-zero cache_ttl"):
        await server_module.browser_crawl("https://example.com", no_cache=True, cache_ttl=60)
    with pytest.raises(ValueError, match="mutually exclusive"):
        await server_module.browser_crawl(
            "https://example.com", timeout=1_000, goto_options={"timeout": 2_000}
        )
    with pytest.raises(ValueError, match="mutually exclusive"):
        await server_module.browser_crawl(
            "https://example.com",
            viewport_width=800,
            viewport_height=600,
            viewport={"width": 800, "height": 600},
        )


@pytest.mark.asyncio
async def test_interaction_tools_forward_injection_controls(monkeypatch):
    captured = None

    class Client:
        async def click(self, _url, _selector, **kwargs):
            nonlocal captured
            captured = kwargs
            return {"url": "https://example.com"}

    monkeypatch.setattr(server_module, "get_client", lambda: Client())
    await server_module.browser_click(
        "https://example.com",
        "button",
        authenticate={"username": "user", "password": "pass"},
        add_style_tag=[{"content": "body { color: red }"}],
        reject_resource_types=["image"],
    )
    assert captured == {
        "authenticate": {"username": "user", "password": "pass"},
        "add_style_tag": [{"content": "body { color: red }"}],
        "reject_resource_types": ["image"],
    }


@pytest.mark.asyncio
async def test_screenshot_artifacts_are_private_unique_and_hide_userinfo(monkeypatch):
    class Client:
        async def screenshot(self, *_args, **_kwargs):
            return b"png"

    monkeypatch.setattr(server_module, "get_client", lambda: Client())
    first = Path(
        await server_module.browser_screenshot("https://username:password@example.com/private")
    )
    second = Path(
        await server_module.browser_screenshot("https://username:password@example.com/private")
    )
    assert first != second
    assert first.name.startswith("example.com_")
    assert "username" not in first.name and "password" not in first.name
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert stat.S_IMODE(first.parent.stat().st_mode) == 0o700
    server_module._cleanup_artifacts()


def test_artifact_quota_evicts_old_files_and_rejects_oversized(monkeypatch):
    server_module._cleanup_artifacts()
    monkeypatch.setattr(server_module, "_MAX_ARTIFACT_COUNT", 2)
    monkeypatch.setattr(server_module, "_MAX_ARTIFACT_TOTAL_BYTES", 8)
    monkeypatch.setattr(server_module, "_MAX_ARTIFACT_BYTES", 6)

    first = Path(server_module._write_artifact("https://example.com", b"1111", ".png"))
    second = Path(server_module._write_artifact("https://example.com", b"22", ".png"))
    first.touch()
    second.touch()
    third = Path(server_module._write_artifact("https://example.com", b"3333", ".png"))

    assert not first.exists()
    assert second.exists()
    assert third.exists()
    with pytest.raises(ValueError, match="maximum artifact size"):
        server_module._write_artifact("https://example.com", b"1234567", ".pdf")
    server_module._cleanup_artifacts()


def test_artifact_filename_prefix_is_bounded_for_maximum_length_hostname(monkeypatch):
    server_module._cleanup_artifacts()
    monkeypatch.setattr(server_module, "_MAX_ARTIFACT_BYTES", 64)
    hostname = ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61])

    path = Path(server_module._write_artifact(f"https://{hostname}", b"png", ".png"))

    assert len(path.name.encode()) <= 255
    server_module._cleanup_artifacts()


@pytest.mark.asyncio
async def test_crawl_status_forwards_pagination(monkeypatch):
    captured = None

    class Client:
        async def crawl_status(self, _job_id, **kwargs):
            nonlocal captured
            captured = kwargs
            return {"status": "completed", "records": []}

    monkeypatch.setattr(server_module, "get_client", lambda: Client())
    await server_module.browser_crawl_status("job-id", cursor="next", limit=25, status="completed")
    assert captured == {"cursor": "next", "limit": 25, "status": "completed"}

    await server_module.browser_crawl_status("job-id", cursor=10)
    assert captured == {"cursor": 10, "limit": None, "status": None}


@pytest.mark.asyncio
async def test_crawl_wait_only_converts_terminal_job_errors(monkeypatch):
    class FailedJobClient:
        async def crawl_wait(self, *_args, **_kwargs):
            raise CrawlJobError("cancelled_by_user")

    monkeypatch.setattr(server_module, "get_client", lambda: FailedJobClient())
    body = json.loads(await server_module.browser_crawl_status("job-id", wait=True))
    assert body["status"] == "failed"

    class TransportFailureClient:
        async def crawl_wait(self, *_args, **_kwargs):
            raise TransportError("offline")

    monkeypatch.setattr(server_module, "get_client", lambda: TransportFailureClient())
    with pytest.raises(TransportError, match="offline"):
        await server_module.browser_crawl_status("job-id", wait=True)


@pytest.mark.asyncio
async def test_browser_click_returns_deploy_hint_for_missing_route(monkeypatch):
    class MissingRouteClient:
        async def click(self, *_args, **_kwargs):
            raise NotFoundError("Not found", status_code=404)

    monkeypatch.setattr(server_module, "get_client", lambda: MissingRouteClient())

    body = json.loads(await server_module.browser_click("https://example.com", "button"))
    assert body["error"] == "Not found"
    assert "Redeploy the Worker" in body["hint"]


@pytest.mark.asyncio
async def test_browser_type_preserves_direct_mode_hint(monkeypatch):
    class DirectModeClient:
        async def type_text(self, *_args, **_kwargs):
            raise NotImplementedError("interaction unsupported")

    monkeypatch.setattr(server_module, "get_client", lambda: DirectModeClient())

    body = json.loads(
        await server_module.browser_type(
            "https://example.com",
            "#email",
            "user@example.com",
        )
    )
    assert body["error"] == "interaction unsupported"
    assert body["hint"] == "Use Worker mode with BROWSER binding"


@pytest.mark.asyncio
async def test_browser_click_returns_binding_hint_for_501(monkeypatch):
    class MissingBindingClient:
        async def click(self, *_args, **_kwargs):
            raise BrowserUnavailableError("binding unavailable", status_code=501)

    monkeypatch.setattr(server_module, "get_client", lambda: MissingBindingClient())

    body = json.loads(await server_module.browser_click("https://example.com", "button"))
    assert body["error"] == "binding unavailable"
    assert body["hint"] == "Enable the Worker BROWSER binding"
