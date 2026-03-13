"""
Tests for CFBrowser SDK client.
Uses respx to mock httpx requests.
"""
import asyncio
import json
import pytest
import respx
import httpx

from cf_browser import CFBrowser
from cf_browser.exceptions import AuthenticationError, RateLimitError, CFBrowserError
from cf_browser.models import LinkItem, CrawlJob, CrawlResult


BASE_URL = "https://cf-browser.example.workers.dev"
API_KEY = "test-api-key-123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return CFBrowser(base_url=BASE_URL, api_key=API_KEY)


# ---------------------------------------------------------------------------
# content()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_content_returns_string(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/content").mock(
            return_value=httpx.Response(200, text="<html>hello</html>")
        )
        result = await client.content("https://example.com")
    assert isinstance(result, str)
    assert "hello" in result


@pytest.mark.asyncio
async def test_content_sends_url_in_body(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content("https://example.com")
    sent = json.loads(route.calls[0].request.content)
    assert sent["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_content_sends_auth_header(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content("https://example.com")
    assert route.calls[0].request.headers["authorization"] == f"Bearer {API_KEY}"


@pytest.mark.asyncio
async def test_content_no_cache_flag(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content("https://example.com", no_cache=True)
    sent = json.loads(route.calls[0].request.content)
    assert sent.get("no_cache") is True


# ---------------------------------------------------------------------------
# screenshot()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_screenshot_returns_bytes(client):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    with respx.mock:
        respx.post(f"{BASE_URL}/screenshot").mock(
            return_value=httpx.Response(200, content=png_bytes)
        )
        result = await client.screenshot("https://example.com")
    assert isinstance(result, bytes)
    assert result == png_bytes


@pytest.mark.asyncio
async def test_screenshot_passes_opts(client):
    png_bytes = b"\x89PNG"
    with respx.mock:
        route = respx.post(f"{BASE_URL}/screenshot").mock(
            return_value=httpx.Response(200, content=png_bytes)
        )
        await client.screenshot("https://example.com", width=1280, height=720)
    sent = json.loads(route.calls[0].request.content)
    assert sent["width"] == 1280
    assert sent["height"] == 720


# ---------------------------------------------------------------------------
# pdf()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pdf_returns_bytes(client):
    pdf_bytes = b"%PDF-1.4" + b"\x00" * 10
    with respx.mock:
        respx.post(f"{BASE_URL}/pdf").mock(
            return_value=httpx.Response(200, content=pdf_bytes)
        )
        result = await client.pdf("https://example.com")
    assert isinstance(result, bytes)
    assert result == pdf_bytes


# ---------------------------------------------------------------------------
# markdown()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_markdown_returns_string(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/markdown").mock(
            return_value=httpx.Response(200, text="# Hello World")
        )
        result = await client.markdown("https://example.com")
    assert isinstance(result, str)
    assert result == "# Hello World"


# ---------------------------------------------------------------------------
# snapshot()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_returns_dict(client):
    payload = {"html": "<html/>", "screenshot": "base64data"}
    with respx.mock:
        respx.post(f"{BASE_URL}/snapshot").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.snapshot("https://example.com")
    assert isinstance(result, dict)
    assert result["html"] == "<html/>"


# ---------------------------------------------------------------------------
# scrape()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_returns_dict(client):
    payload = {"elements": [{"selector": "h1", "text": "Title"}]}
    with respx.mock:
        route = respx.post(f"{BASE_URL}/scrape").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.scrape("https://example.com", selectors=["h1", "p"])
    assert isinstance(result, dict)
    assert "elements" in result
    sent = json.loads(route.calls[0].request.content)
    assert sent["elements"] == ["h1", "p"]


# ---------------------------------------------------------------------------
# json_extract()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_json_extract_returns_dict(client):
    payload = {"name": "John", "age": 30}
    with respx.mock:
        route = respx.post(f"{BASE_URL}/json").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.json_extract("https://example.com", prompt="Extract name and age")
    assert isinstance(result, dict)
    assert result["name"] == "John"
    sent = json.loads(route.calls[0].request.content)
    assert sent["prompt"] == "Extract name and age"


# ---------------------------------------------------------------------------
# links()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_links_returns_list(client):
    payload = [{"href": "https://a.com", "text": "A"}, {"href": "https://b.com", "text": "B"}]
    with respx.mock:
        respx.post(f"{BASE_URL}/links").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.links("https://example.com")
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["href"] == "https://a.com"


# ---------------------------------------------------------------------------
# a11y()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a11y_returns_dict(client):
    payload = {"url": "https://example.com", "title": "Example", "nodes": []}
    with respx.mock:
        respx.post(f"{BASE_URL}/a11y").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.a11y("https://example.com")
    assert isinstance(result, dict)
    assert result["title"] == "Example"


@pytest.mark.asyncio
async def test_a11y_sends_wait_for(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/a11y").mock(
            return_value=httpx.Response(200, json={"title": "Test"})
        )
        await client.a11y("https://example.com", wait_for="main")
    sent = json.loads(route.calls[0].request.content)
    assert sent["wait_for"] == "main"


# ---------------------------------------------------------------------------
# Cookies and headers support
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cookies_forwarded_in_body(client):
    cookies = [{"name": "session", "value": "abc", "domain": ".example.com"}]
    with respx.mock:
        route = respx.post(f"{BASE_URL}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content("https://example.com", cookies=cookies)
    sent = json.loads(route.calls[0].request.content)
    assert sent["cookies"] == cookies


@pytest.mark.asyncio
async def test_custom_headers_forwarded_in_body(client):
    custom_headers = {"X-Auth": "token123", "Accept-Language": "en"}
    with respx.mock:
        route = respx.post(f"{BASE_URL}/markdown").mock(
            return_value=httpx.Response(200, text="# Hello")
        )
        await client.markdown("https://example.com", headers=custom_headers)
    sent = json.loads(route.calls[0].request.content)
    assert sent["headers"] == custom_headers


@pytest.mark.asyncio
async def test_cookies_and_headers_together(client):
    cookies = [{"name": "sid", "value": "xyz"}]
    custom_headers = {"X-Token": "abc"}
    with respx.mock:
        route = respx.post(f"{BASE_URL}/screenshot").mock(
            return_value=httpx.Response(200, content=b"\x89PNG")
        )
        await client.screenshot(
            "https://example.com",
            cookies=cookies,
            headers=custom_headers,
        )
    sent = json.loads(route.calls[0].request.content)
    assert sent["cookies"] == cookies
    assert sent["headers"] == custom_headers


# ---------------------------------------------------------------------------
# crawl() and crawl_status()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crawl_raises_on_missing_job_id(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/crawl").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        with pytest.raises(CFBrowserError, match="missing job_id"):
            await client.crawl("https://example.com")


@pytest.mark.asyncio
async def test_crawl_returns_job_id(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/crawl").mock(
            return_value=httpx.Response(200, json={"job_id": "abc-123"})
        )
        job_id = await client.crawl("https://example.com")
    assert job_id == "abc-123"


@pytest.mark.asyncio
async def test_crawl_status_returns_dict(client):
    payload = {"job_id": "abc-123", "status": "running"}
    with respx.mock:
        respx.get(f"{BASE_URL}/crawl/abc-123").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = await client.crawl_status("abc-123")
    assert result["status"] == "running"


# ---------------------------------------------------------------------------
# crawl_wait() - polling logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crawl_wait_polls_until_complete(client):
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(200, json={"job_id": "abc-123", "status": "running"})
        return httpx.Response(200, json={"job_id": "abc-123", "status": "complete", "pages": []})

    with respx.mock:
        respx.get(f"{BASE_URL}/crawl/abc-123").mock(side_effect=side_effect)
        result = await client.crawl_wait("abc-123", timeout=60, poll_interval=0.01)

    assert result["status"] == "complete"
    assert call_count == 3


@pytest.mark.asyncio
async def test_crawl_wait_raises_on_timeout(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/crawl/abc-123").mock(
            return_value=httpx.Response(200, json={"job_id": "abc-123", "status": "running"})
        )
        with pytest.raises(TimeoutError):
            await client.crawl_wait("abc-123", timeout=0.05, poll_interval=0.01)


@pytest.mark.asyncio
async def test_crawl_wait_raises_on_failed_status(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/crawl/abc-123").mock(
            return_value=httpx.Response(
                200, json={"job_id": "abc-123", "status": "failed", "error": "Timeout"}
            )
        )
        with pytest.raises(CFBrowserError, match="Crawl job failed"):
            await client.crawl_wait("abc-123", timeout=60, poll_interval=0.01)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_401_raises_authentication_error(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/content").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"})
        )
        with pytest.raises(AuthenticationError):
            await client.content("https://example.com")


@pytest.mark.asyncio
async def test_429_raises_rate_limit_error(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/content").mock(
            return_value=httpx.Response(429, json={"error": "Rate limit exceeded"})
        )
        with pytest.raises(RateLimitError):
            await client.content("https://example.com")


@pytest.mark.asyncio
async def test_500_raises_cf_browser_error(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/content").mock(
            return_value=httpx.Response(500, json={"error": "Internal server error"})
        )
        with pytest.raises(CFBrowserError):
            await client.content("https://example.com")


@pytest.mark.asyncio
async def test_404_raises_not_found_error(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/content").mock(
            return_value=httpx.Response(404, json={"error": "Not found"})
        )
        from cf_browser.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            await client.content("https://example.com")


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_manager():
    with respx.mock:
        respx.post(f"{BASE_URL}/markdown").mock(
            return_value=httpx.Response(200, text="# Test")
        )
        async with CFBrowser(base_url=BASE_URL, api_key=API_KEY) as browser:
            result = await browser.markdown("https://example.com")
    assert result == "# Test"


@pytest.mark.asyncio
async def test_context_manager_closes_client():
    browser = CFBrowser(base_url=BASE_URL, api_key=API_KEY)
    async with browser:
        pass
    # After exiting context, the internal httpx client should be closed
    assert browser._client.is_closed


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def test_link_item_model():
    item = LinkItem(href="https://example.com", text="Example")
    assert item.href == "https://example.com"
    assert item.text == "Example"


def test_link_item_text_optional():
    item = LinkItem(href="https://example.com")
    assert item.text is None


def test_crawl_job_model():
    job = CrawlJob(job_id="abc-123", status="pending")
    assert job.job_id == "abc-123"
    assert job.status == "pending"


def test_crawl_result_model():
    result = CrawlResult(
        job_id="abc-123",
        status="complete",
        pages=[{"url": "https://example.com", "content": "hello"}],
    )
    assert result.status == "complete"
    assert len(result.pages) == 1


def test_crawl_result_optional_fields():
    result = CrawlResult(job_id="abc-123", status="failed", error="Timeout")
    assert result.pages is None
    assert result.error == "Timeout"
