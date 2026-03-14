"""
Tests for CFBrowserDirect — direct CF API mode (no Worker).
Uses respx to mock httpx requests.
"""
import json

import httpx
import pytest
import respx

from cf_browser import CFBrowserDirect
from cf_browser.exceptions import AuthenticationError, CFBrowserError, RateLimitError

ACCOUNT_ID = "test-account-123"
API_TOKEN = "test-token-456"
CF_BASE = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/browser-rendering"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return CFBrowserDirect(account_id=ACCOUNT_ID, api_token=API_TOKEN)


# ---------------------------------------------------------------------------
# content()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_returns_string(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(200, text="<html>hello</html>")
        )
        result = await client.content("https://example.com")
    assert isinstance(result, str)
    assert "hello" in result


@pytest.mark.asyncio
async def test_content_sends_bearer_token(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content("https://example.com")
    assert route.calls[0].request.headers["authorization"] == f"Bearer {API_TOKEN}"


@pytest.mark.asyncio
async def test_content_strips_no_cache(client):
    """no_cache is a Worker feature — direct mode should strip it."""
    with respx.mock:
        route = respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content("https://example.com", no_cache=True)
    sent = json.loads(route.calls[0].request.content)
    assert "no_cache" not in sent


@pytest.mark.asyncio
async def test_content_unwraps_cf_envelope(client):
    """CF API may wrap responses in {success, result} — should unwrap."""
    with respx.mock:
        respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(
                200,
                json={"success": True, "result": "<html>wrapped</html>"},
                headers={"content-type": "application/json"},
            )
        )
        result = await client.content("https://example.com")
    assert "wrapped" in result


# ---------------------------------------------------------------------------
# markdown()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_markdown_returns_string(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/markdown").mock(
            return_value=httpx.Response(200, text="# Hello World")
        )
        result = await client.markdown("https://example.com")
    assert result == "# Hello World"


# ---------------------------------------------------------------------------
# screenshot() — param transformation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_screenshot_returns_bytes(client):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    with respx.mock:
        respx.post(f"{CF_BASE}/screenshot").mock(
            return_value=httpx.Response(200, content=png_bytes)
        )
        result = await client.screenshot("https://example.com")
    assert isinstance(result, bytes)
    assert result == png_bytes


@pytest.mark.asyncio
async def test_screenshot_transforms_viewport(client):
    """width/height should be mapped to CF API's viewport object."""
    with respx.mock:
        route = respx.post(f"{CF_BASE}/screenshot").mock(
            return_value=httpx.Response(200, content=b"\x89PNG")
        )
        await client.screenshot("https://example.com", width=1280, height=720)
    sent = json.loads(route.calls[0].request.content)
    assert sent["viewport"] == {"width": 1280, "height": 720}
    assert "width" not in sent
    assert "height" not in sent


@pytest.mark.asyncio
async def test_screenshot_transforms_full_page(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/screenshot").mock(
            return_value=httpx.Response(200, content=b"\x89PNG")
        )
        await client.screenshot("https://example.com", full_page=True)
    sent = json.loads(route.calls[0].request.content)
    assert sent["screenshotOptions"] == {"fullPage": True}
    assert "full_page" not in sent


# ---------------------------------------------------------------------------
# pdf() — param transformation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_returns_bytes(client):
    pdf_bytes = b"%PDF-1.4" + b"\x00" * 10
    with respx.mock:
        respx.post(f"{CF_BASE}/pdf").mock(
            return_value=httpx.Response(200, content=pdf_bytes)
        )
        result = await client.pdf("https://example.com")
    assert isinstance(result, bytes)


@pytest.mark.asyncio
async def test_pdf_transforms_options(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/pdf").mock(
            return_value=httpx.Response(200, content=b"%PDF")
        )
        await client.pdf("https://example.com", format="Letter", landscape=True)
    sent = json.loads(route.calls[0].request.content)
    assert sent["pdfOptions"] == {"format": "Letter", "landscape": True}
    assert "format" not in sent
    assert "landscape" not in sent


# ---------------------------------------------------------------------------
# scrape() — selector transformation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_transforms_selectors(client):
    """String selectors should become [{selector: "..."}] objects."""
    with respx.mock:
        route = respx.post(f"{CF_BASE}/scrape").mock(
            return_value=httpx.Response(
                200, json={"success": True, "result": {"elements": []}}
            )
        )
        await client.scrape("https://example.com", selectors=["h1", "p"])
    sent = json.loads(route.calls[0].request.content)
    assert sent["elements"] == [{"selector": "h1"}, {"selector": "p"}]


# ---------------------------------------------------------------------------
# json_extract()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_json_extract_returns_dict(client):
    payload = {"success": True, "result": {"name": "John"}}
    with respx.mock:
        respx.post(f"{CF_BASE}/json").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.json_extract("https://example.com", prompt="Extract name")
    assert result == {"name": "John"}


# ---------------------------------------------------------------------------
# links()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_links_returns_list(client):
    payload = {"success": True, "result": [{"href": "https://a.com"}]}
    with respx.mock:
        respx.post(f"{CF_BASE}/links").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.links("https://example.com")
    assert isinstance(result, list)
    assert result[0]["href"] == "https://a.com"


# ---------------------------------------------------------------------------
# a11y() — uses /snapshot internally
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a11y_strips_screenshot(client):
    """a11y should call /snapshot but strip the screenshot field."""
    snapshot = {"html": "<html/>", "screenshot": "base64...", "title": "Test"}
    with respx.mock:
        respx.post(f"{CF_BASE}/snapshot").mock(
            return_value=httpx.Response(
                200, json={"success": True, "result": snapshot}
            )
        )
        result = await client.a11y("https://example.com")
    assert result["type"] == "accessibility_snapshot"
    assert result["title"] == "Test"
    assert "screenshot" not in result


# ---------------------------------------------------------------------------
# crawl()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_returns_job_id(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/crawl").mock(
            return_value=httpx.Response(
                200, json={"success": True, "result": {"id": "job-abc"}}
            )
        )
        job_id = await client.crawl("https://example.com")
    assert job_id == "job-abc"


@pytest.mark.asyncio
async def test_crawl_maps_max_pages_to_limit(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/crawl").mock(
            return_value=httpx.Response(
                200, json={"success": True, "result": {"id": "j1"}}
            )
        )
        await client.crawl("https://example.com", max_pages=5)
    sent = json.loads(route.calls[0].request.content)
    assert sent["limit"] == 5
    assert "max_pages" not in sent


@pytest.mark.asyncio
async def test_crawl_status_returns_dict(client):
    payload = {"success": True, "result": {"id": "abc", "status": "running"}}
    with respx.mock:
        respx.get(f"{CF_BASE}/crawl/abc").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.crawl_status("abc")
    assert result["status"] == "running"


# ---------------------------------------------------------------------------
# crawl_wait()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_wait_polls_until_complete(client):
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(
                200, json={"success": True, "result": {"id": "j1", "status": "running"}}
            )
        return httpx.Response(
            200,
            json={"success": True, "result": {"id": "j1", "status": "complete", "pages": []}},
        )

    with respx.mock:
        respx.get(f"{CF_BASE}/crawl/j1").mock(side_effect=side_effect)
        result = await client.crawl_wait("j1", timeout=60, poll_interval=0.01)

    assert result["status"] == "complete"
    assert call_count == 3


@pytest.mark.asyncio
async def test_crawl_wait_raises_on_timeout(client):
    with respx.mock:
        respx.get(f"{CF_BASE}/crawl/j1").mock(
            return_value=httpx.Response(
                200, json={"success": True, "result": {"id": "j1", "status": "running"}}
            )
        )
        with pytest.raises(TimeoutError):
            await client.crawl_wait("j1", timeout=0.05, poll_interval=0.01)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_401_raises_authentication_error(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(
                401,
                json={"success": False, "errors": [{"message": "Invalid token"}]},
            )
        )
        with pytest.raises(AuthenticationError):
            await client.content("https://example.com")


@pytest.mark.asyncio
async def test_429_raises_rate_limit_error(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(429, json={"error": "Rate limited"})
        )
        with pytest.raises(RateLimitError):
            await client.content("https://example.com")


@pytest.mark.asyncio
async def test_500_raises_cf_browser_error(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(CFBrowserError):
            await client.content("https://example.com")


# ---------------------------------------------------------------------------
# Cookies and headers (pass-through)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cookies_forwarded(client):
    cookies = [{"name": "session", "value": "abc", "domain": ".example.com"}]
    with respx.mock:
        route = respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content("https://example.com", cookies=cookies)
    sent = json.loads(route.calls[0].request.content)
    assert sent["cookies"] == cookies


@pytest.mark.asyncio
async def test_custom_headers_forwarded(client):
    custom_headers = {"X-Auth": "token123"}
    with respx.mock:
        route = respx.post(f"{CF_BASE}/markdown").mock(
            return_value=httpx.Response(200, text="# Hello")
        )
        await client.markdown("https://example.com", headers=custom_headers)
    sent = json.loads(route.calls[0].request.content)
    assert sent["headers"] == custom_headers


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_manager():
    with respx.mock:
        respx.post(f"{CF_BASE}/markdown").mock(
            return_value=httpx.Response(200, text="# Test")
        )
        async with CFBrowserDirect(account_id=ACCOUNT_ID, api_token=API_TOKEN) as browser:
            result = await browser.markdown("https://example.com")
    assert result == "# Test"


@pytest.mark.asyncio
async def test_context_manager_closes_client():
    browser = CFBrowserDirect(account_id=ACCOUNT_ID, api_token=API_TOKEN)
    async with browser:
        pass
    assert browser._client.is_closed
