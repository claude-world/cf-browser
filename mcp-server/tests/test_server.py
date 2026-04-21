"""Smoke tests for the MCP server — verify tools are registered correctly.

Note: These tests access FastMCP internals (_tool_manager._tools) which
may break on FastMCP version upgrades. If tests fail after an MCP library
update, check for changes to the internal registry API.
"""

import json

import pytest

from cf_browser.exceptions import NotFoundError
import cf_browser_mcp.server as server_module

from cf_browser_mcp.server import mcp


def test_server_has_expected_tool_count():
    """The MCP server should expose exactly 15 browser tools."""
    tools = mcp._tool_manager._tools  # FastMCP internal registry
    assert len(tools) == 15


def test_all_tool_names_present():
    """Every tool name should match a browser_* convention."""
    tools = mcp._tool_manager._tools
    expected = {
        # Read-only tools
        "browser_content",
        "browser_screenshot",
        "browser_pdf",
        "browser_markdown",
        "browser_scrape",
        "browser_json",
        "browser_links",
        "browser_crawl",
        "browser_crawl_status",
        "browser_a11y",
        # Interaction tools
        "browser_click",
        "browser_type",
        "browser_evaluate",
        "browser_interact",
        "browser_submit_form",
    }
    assert set(tools.keys()) == expected


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
