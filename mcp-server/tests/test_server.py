"""Smoke tests for the MCP server — verify tools are registered correctly.

Note: These tests access FastMCP internals (_tool_manager._tools) which
may break on FastMCP version upgrades. If tests fail after an MCP library
update, check for changes to the internal registry API.
"""

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
