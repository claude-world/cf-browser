"""
Tests for CFBrowserDirect — direct CF API mode (no Worker).
Uses respx to mock httpx requests.
"""

import json
import time

import httpx
import pytest
import respx

from cf_browser import CFBrowserDirect
from cf_browser.exceptions import (
    AuthenticationError,
    CFBrowserError,
    RateLimitError,
    TransportError,
)

ACCOUNT_ID = "test-account-123"
API_TOKEN = "test-token-456"
CF_BASE = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/browser-rendering"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return CFBrowserDirect(account_id=ACCOUNT_ID, api_token=API_TOKEN)


@pytest.mark.parametrize(
    ("account_id", "api_token", "message"),
    [("", API_TOKEN, "account_id"), (ACCOUNT_ID, "", "api_token")],
)
def test_constructor_rejects_missing_credentials(account_id, api_token, message):
    with pytest.raises(ValueError, match=message):
        CFBrowserDirect(account_id=account_id, api_token=api_token)


@pytest.mark.parametrize(
    ("account_id", "timeout", "message"),
    [
        ("../other-account", 60, "account_id"),
        (ACCOUNT_ID, True, "timeout must be greater"),
        (ACCOUNT_ID, float("inf"), "timeout must be greater"),
    ],
)
def test_constructor_rejects_invalid_transport_configuration(account_id, timeout, message):
    with pytest.raises(ValueError, match=message):
        CFBrowserDirect(account_id=account_id, api_token=API_TOKEN, timeout=timeout)


def test_default_transport_timeout_covers_current_synchronous_actions(client):
    assert client._client.timeout.read == 310.0


@pytest.mark.parametrize("api_token", [" secret-token", "secret-token\r\n", "secret\ttoken"])
def test_constructor_rejects_header_unsafe_tokens_without_echoing_them(api_token):
    with pytest.raises(ValueError, match="visible ASCII") as exc_info:
        CFBrowserDirect(account_id=ACCOUNT_ID, api_token=api_token)
    assert "secret" not in str(exc_info.value)


def test_connect_timeout_fails_fast_without_shortening_actions(client):
    assert client._client.timeout.connect == 10.0


@pytest.mark.asyncio
async def test_local_protocol_errors_are_never_echoed(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/content").mock(
            side_effect=httpx.LocalProtocolError("Illegal header value b'Bearer leaked-secret'")
        )
        with pytest.raises(TransportError) as exc_info:
            await client.content("https://example.com")
    assert "leaked-secret" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize("job_id", [".", ".."])
async def test_crawl_job_ids_cannot_escape_the_crawl_path(client, job_id):
    with pytest.raises(ValueError, match="relative path segment"):
        await client.crawl_status(job_id)
    with pytest.raises(ValueError, match="relative path segment"):
        await client.delete_crawl(job_id)


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
@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"no_cache": "yes"}, "no_cache must be a boolean"),
        ({"wait_for": ""}, "wait_for must be a non-empty string"),
        ({"timeout": True}, "timeout must be an integer"),
        ({"wait_until": []}, "wait_until must be"),
        ({"user_agent": 42}, "user_agent must be a non-empty string"),
        ({"headers": {"X-Test": 1}}, "headers must be a dictionary"),
        ({"cookies": [{"name": "session"}]}, "cookies must be a list"),
        ({"authenticate": {"username": "user"}}, "authenticate must contain"),
        ({"add_script_tag": [{}]}, "add_script_tag must be a list"),
        ({"reject_resource_types": [""]}, "reject_resource_types must be a list"),
        ({"timeout": 1000, "gotoOptions": []}, "gotoOptions must be a dictionary"),
        (
            {"gotoOptions": {"waitUntil": [{"event": "load"}]}},
            "gotoOptions.waitUntil contains an unsupported lifecycle event",
        ),
    ],
)
async def test_content_rejects_invalid_common_options(client, options, message):
    with pytest.raises(ValueError, match=message):
        await client.content("https://example.com", **options)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"waitForSelector": "#app"}, "waitForSelector must be a dictionary"),
        ({"waitForSelector": {}}, "waitForSelector.selector"),
        ({"waitForSelector": {"selector": "", "timeout": 1000}}, "selector"),
        ({"waitForSelector": {"selector": "#app", "timeout": True}}, "timeout"),
        ({"waitForSelector": {"selector": "#app", "timeout": None}}, "timeout"),
        ({"waitForSelector": {"selector": "#app", "timeout": 120_001}}, "timeout"),
        ({"waitForSelector": {"selector": "#app", "hidden": None}}, "hidden"),
        ({"actionTimeout": True}, "actionTimeout"),
        ({"actionTimeout": 120_001}, "actionTimeout"),
        ({"waitForTimeout": 0}, "waitForTimeout"),
        ({"waitForTimeout": 120_001}, "waitForTimeout"),
        ({"gotoOptions": None}, "gotoOptions must be a dictionary"),
        ({"gotoOptions": {"referer": 42}}, "gotoOptions.referer"),
        ({"viewport": None}, "viewport must be a dictionary"),
        ({"viewport": {"width": 7_681}}, "viewport.width"),
        ({"bestAttempt": None}, "bestAttempt"),
        ({"setJavaScriptEnabled": "yes"}, "setJavaScriptEnabled"),
        ({"emulateMediaType": ""}, "emulateMediaType"),
        ({"rejectRequestPattern": [""]}, "rejectRequestPattern"),
        ({"allowResourceTypes": ["not-a-resource"]}, "allowResourceTypes"),
    ],
)
async def test_content_rejects_invalid_raw_canonical_options(client, options, message):
    with pytest.raises(ValueError, match=message):
        await client.content("https://example.com", **options)


@pytest.mark.asyncio
async def test_content_forwards_valid_raw_canonical_options(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content(
            "https://example.com",
            waitForSelector={"selector": "#app", "timeout": 120_000, "hidden": True},
            actionTimeout=120_000,
            waitForTimeout=120_000,
            gotoOptions={"referer": "https://example.com/source"},
            viewport={"width": 1280, "height": 720, "deviceScaleFactor": 2},
            bestAttempt=True,
            setJavaScriptEnabled=False,
            emulateMediaType="screen",
            rejectRequestPattern=["*.png"],
            allowResourceTypes=["document", "xhr"],
        )
    sent = json.loads(route.calls[0].request.content)
    assert sent["waitForSelector"]["selector"] == "#app"
    assert sent["actionTimeout"] == 120_000
    assert sent["waitForTimeout"] == 120_000
    assert sent["viewport"]["width"] == 1280
    assert sent["bestAttempt"] is True


@pytest.mark.asyncio
async def test_content_rejects_empty_url(client):
    with pytest.raises(ValueError, match="url must be a non-empty string"):
        await client.content("")


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


@pytest.mark.asyncio
async def test_content_rejects_non_string_success_result(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(
                200,
                json={"success": True, "result": {"html": "<html>wrong shape</html>"}},
                headers={"content-type": "application/json"},
            )
        )
        with pytest.raises(CFBrowserError, match="malformed content"):
            await client.content("https://example.com")


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


@pytest.mark.asyncio
async def test_snapshot_rejects_non_object_response(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/snapshot").mock(
            return_value=httpx.Response(
                200,
                json={"success": True, "result": ["wrong shape"]},
                headers={"content-type": "application/json"},
            )
        )
        with pytest.raises(CFBrowserError, match="malformed snapshot"):
            await client.snapshot("https://example.com")


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
async def test_screenshot_rejects_http_200_error_envelope(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/screenshot").mock(
            return_value=httpx.Response(
                200,
                json={"success": False, "errors": [{"message": "Capture failed"}]},
                headers={"Content-Type": "application/json"},
            )
        )
        with pytest.raises(CFBrowserError, match="Capture failed"):
            await client.screenshot("https://example.com")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "method"),
    [("screenshot", "screenshot"), ("pdf", "pdf")],
)
async def test_binary_endpoints_reject_json_success_objects(client, endpoint, method):
    with respx.mock:
        respx.post(f"{CF_BASE}/{endpoint}").mock(
            return_value=httpx.Response(
                200,
                json={"success": True, "result": {"unexpected": "object"}},
                headers={"Content-Type": "application/json"},
            )
        )
        with pytest.raises(CFBrowserError, match="binary endpoint") as exc_info:
            await getattr(client, method)("https://example.com")
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "method", "content"),
    [
        ("screenshot", "screenshot", b"not-an-image"),
        ("pdf", "pdf", b"not-a-pdf"),
    ],
)
async def test_binary_endpoints_reject_invalid_magic(client, endpoint, method, content):
    with respx.mock:
        respx.post(f"{CF_BASE}/{endpoint}").mock(return_value=httpx.Response(200, content=content))
        with pytest.raises(CFBrowserError, match="malformed") as exc_info:
            await getattr(client, method)("https://example.com")
    assert exc_info.value.status_code == 502


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


@pytest.mark.asyncio
async def test_screenshot_preserves_existing_nested_options(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/screenshot").mock(
            return_value=httpx.Response(200, content=b"\x89PNG")
        )
        await client.screenshot(
            "https://example.com",
            width=1280,
            full_page=True,
            viewport={"height": 900, "deviceScaleFactor": 2},
            screenshotOptions={"omitBackground": True},
        )
    sent = json.loads(route.calls[0].request.content)
    assert sent["viewport"] == {"width": 1280, "height": 900, "deviceScaleFactor": 2}
    assert sent["screenshotOptions"] == {"fullPage": True, "omitBackground": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"viewport": []}, "viewport must be a dictionary"),
        ({"screenshotOptions": []}, "screenshotOptions must be a dictionary"),
        (
            {"screenshotOptions": {"encoding": "base64"}},
            "screenshotOptions.encoding must be binary",
        ),
        (
            {"screenshotOptions": {"fullPage": "yes"}},
            "screenshotOptions.fullPage must be a boolean",
        ),
        (
            {"viewport": {"width": 999_999}},
            "viewport.width must be an integer between 1 and 7680",
        ),
    ],
)
async def test_screenshot_rejects_malformed_nested_options(client, options, message):
    with pytest.raises(ValueError, match=message):
        await client.screenshot("https://example.com", **options)


# ---------------------------------------------------------------------------
# pdf() — param transformation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_returns_bytes(client):
    pdf_bytes = b"%PDF-1.4" + b"\x00" * 10
    with respx.mock:
        respx.post(f"{CF_BASE}/pdf").mock(return_value=httpx.Response(200, content=pdf_bytes))
        result = await client.pdf("https://example.com")
    assert isinstance(result, bytes)


@pytest.mark.asyncio
async def test_pdf_maps_supported_options(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/pdf").mock(return_value=httpx.Response(200, content=b"%PDF"))
        await client.pdf("https://example.com", format="Letter", landscape=True)
    sent = json.loads(route.calls[0].request.content)
    assert "format" not in sent
    assert "landscape" not in sent
    assert sent["pdfOptions"] == {"format": "letter", "landscape": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"pdfOptions": {"format": "Poster"}}, "Unsupported pdfOptions.format"),
        (
            {"pdfOptions": {"landscape": "yes"}},
            "pdfOptions.landscape must be a boolean",
        ),
    ],
)
async def test_pdf_rejects_malformed_nested_options(client, options, message):
    with pytest.raises(ValueError, match=message):
        await client.pdf("https://example.com", **options)


# ---------------------------------------------------------------------------
# scrape() — selector transformation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_transforms_selectors(client):
    """String selectors should become [{selector: "..."}] objects."""
    with respx.mock:
        route = respx.post(f"{CF_BASE}/scrape").mock(
            return_value=httpx.Response(
                200, json={"success": True, "result": [{"selector": "h1", "results": []}]}
            )
        )
        result = await client.scrape("https://example.com", selectors=["h1", "p"])
    sent = json.loads(route.calls[0].request.content)
    assert sent["elements"] == [{"selector": "h1"}, {"selector": "p"}]
    assert result["elements"][0]["selector"] == "h1"


# ---------------------------------------------------------------------------
# json_extract()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_json_extract_returns_dict(client):
    payload = {"success": True, "result": {"name": "John"}}
    with respx.mock:
        respx.post(f"{CF_BASE}/json").mock(return_value=httpx.Response(200, json=payload))
        result = await client.json_extract("https://example.com", prompt="Extract name")
    assert result == {"name": "John"}


@pytest.mark.asyncio
async def test_json_extract_maps_schema_alias(client):
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    with respx.mock:
        route = respx.post(f"{CF_BASE}/json").mock(
            return_value=httpx.Response(200, json={"success": True, "result": {"name": "John"}})
        )
        await client.json_extract("https://example.com", schema=schema)
    sent = json.loads(route.calls[0].request.content)
    assert sent["response_format"] == {
        "type": "json_schema",
        "json_schema": schema,
    }
    assert "schema" not in sent


@pytest.mark.asyncio
async def test_json_extract_rejects_malformed_response_format(client):
    with pytest.raises(ValueError, match="type=json_schema"):
        await client.json_extract(
            "https://example.com",
            response_format={"type": "json_schema"},
        )


# ---------------------------------------------------------------------------
# links()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_links_returns_list(client):
    payload = {"success": True, "result": ["https://a.com"]}
    with respx.mock:
        respx.post(f"{CF_BASE}/links").mock(return_value=httpx.Response(200, json=payload))
        result = await client.links("https://example.com")
    assert isinstance(result, list)
    assert result[0]["href"] == "https://a.com"
    assert result[0]["text"] is None


@pytest.mark.asyncio
async def test_links_maps_friendly_filter_options(client):
    payload = {"success": True, "result": []}
    with respx.mock:
        route = respx.post(f"{CF_BASE}/links").mock(return_value=httpx.Response(200, json=payload))
        await client.links("https://example.com", include_external=False, visible_only=True)
    sent = json.loads(route.calls[0].request.content)
    assert sent["excludeExternalLinks"] is True
    assert sent["visibleLinksOnly"] is True
    assert "include_external" not in sent


# ---------------------------------------------------------------------------
# a11y()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a11y_uses_native_accessibility_tree_endpoint(client):
    tree = {
        "type": "upstream-value",
        "accessibilityTree": {"role": "RootWebArea", "name": "Test"},
    }
    with respx.mock:
        respx.post(f"{CF_BASE}/accessibilityTree").mock(
            return_value=httpx.Response(200, json={"success": True, "result": tree})
        )
        result = await client.a11y("https://example.com")
    assert result == {**tree, "type": "accessibility_tree"}


@pytest.mark.asyncio
async def test_a11y_rejects_primitive_response(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/accessibilityTree").mock(
            return_value=httpx.Response(
                200,
                json={"success": True, "result": "wrong shape"},
                headers={"Content-Type": "application/json"},
            )
        )
        with pytest.raises(CFBrowserError, match="malformed accessibility tree") as exc_info:
            await client.a11y("https://example.com")
    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# crawl()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_returns_job_id(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/crawl").mock(
            return_value=httpx.Response(200, json={"success": True, "result": {"id": "job-abc"}})
        )
        job_id = await client.crawl("https://example.com")
    assert job_id == "job-abc"
    sent = json.loads(route.calls[0].request.content)
    assert sent["render"] is True
    assert sent["source"] == "all"
    assert sent["options"] == {
        "includeExternalLinks": False,
        "includeSubdomains": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    ["", "   ", {"id": 123}, {"job_id": []}, {"id": "job-a", "job_id": "job-b"}],
)
async def test_crawl_rejects_malformed_job_ids(client, result):
    with respx.mock:
        respx.post(f"{CF_BASE}/crawl").mock(
            return_value=httpx.Response(200, json={"success": True, "result": result})
        )
        with pytest.raises(CFBrowserError, match="malformed crawl job ID") as exc_info:
            await client.crawl("https://example.com")
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_crawl_maps_max_pages_to_limit(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/crawl").mock(
            return_value=httpx.Response(200, json={"success": True, "result": {"id": "j1"}})
        )
        await client.crawl("https://example.com", max_pages=5)
    sent = json.loads(route.calls[0].request.content)
    assert sent["limit"] == 5
    assert "max_pages" not in sent


@pytest.mark.asyncio
async def test_crawl_rejects_ambiguous_page_limit_aliases(client):
    with pytest.raises(ValueError, match="either max_pages or limit"):
        await client.crawl("https://example.com", max_pages=5, limit=10)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "expected_ttl"),
    [
        ({"no_cache": True}, 0),
        ({"no_cache": True, "cache_ttl": 0}, 0),
        ({"cache_ttl": 0}, 0),
        ({"cache_ttl": 86_400}, 86_400),
    ],
)
async def test_crawl_maps_cache_controls_to_query(client, kwargs, expected_ttl):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/crawl", params={"cacheTTL": expected_ttl}).mock(
            return_value=httpx.Response(200, json={"success": True, "result": "job-cache"})
        )
        await client.crawl("https://example.com", **kwargs)
    sent = json.loads(route.calls[0].request.content)
    assert "no_cache" not in sent
    assert "cache_ttl" not in sent
    assert "cacheTTL" not in sent


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_ttl", [-1, 86_401, True, 1.5])
async def test_crawl_rejects_invalid_cache_ttl(client, cache_ttl):
    with pytest.raises(ValueError, match="cache_ttl must be an integer"):
        await client.crawl("https://example.com", cache_ttl=cache_ttl)


@pytest.mark.asyncio
async def test_crawl_rejects_conflicting_cache_controls(client):
    with pytest.raises(ValueError, match="either no_cache=True or cache_ttl"):
        await client.crawl("https://example.com", no_cache=True, cache_ttl=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("max_pages", [0, True, 100_001])
async def test_crawl_rejects_invalid_max_pages(client, max_pages):
    with pytest.raises(ValueError, match="max_pages must be an integer"):
        await client.crawl("https://example.com", max_pages=max_pages)


@pytest.mark.asyncio
async def test_crawl_rejects_unsupported_user_agent(client):
    with pytest.raises(ValueError, match="not supported"):
        await client.crawl("https://example.com", user_agent="CustomBot/1.0")


@pytest.mark.asyncio
async def test_crawl_rejects_browser_options_when_render_is_false(client):
    with pytest.raises(ValueError, match="render=True"):
        await client.crawl(
            "https://example.com",
            render=False,
            headers={"X-Test": "value"},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"render": "false"}, "render must be a boolean"),
        ({"render": None}, "render must be a boolean"),
        ({"options": []}, "options must be a dictionary"),
        ({"options": None}, "options must be a dictionary"),
        ({"options": {"includeSubdomains": "yes"}}, "must be a boolean"),
        ({"source": "robots"}, "source must be all, links, or sitemaps"),
    ],
)
async def test_crawl_rejects_malformed_current_options(client, options, message):
    with pytest.raises(ValueError, match=message):
        await client.crawl("https://example.com", **options)


@pytest.mark.asyncio
async def test_crawl_maps_current_contract(client):
    modified_since = int(time.time()) - 3600
    with respx.mock:
        route = respx.post(f"{CF_BASE}/crawl").mock(
            return_value=httpx.Response(200, json={"success": True, "result": "job-current"})
        )
        await client.crawl(
            "https://example.com/docs/",
            depth=3,
            formats=["markdown", "json"],
            crawl_purposes=["search"],
            max_age=3600,
            modified_since=modified_since,
            include_external=True,
            include_subdomains=True,
            include_patterns=["**/docs/**"],
            exclude_patterns=["**/private/**"],
            json_options={"prompt": "Extract the title"},
            reject_request_patterns=["*.png"],
            javascript_enabled=False,
        )
    sent = json.loads(route.calls[0].request.content)
    assert sent == {
        "url": "https://example.com/docs/",
        "depth": 3,
        "formats": ["markdown", "json"],
        "crawlPurposes": ["search"],
        "maxAge": 3600,
        "modifiedSince": modified_since,
        "render": True,
        "source": "all",
        "options": {
            "includeExternalLinks": True,
            "includeSubdomains": True,
            "includePatterns": ["**/docs/**"],
            "excludePatterns": ["**/private/**"],
        },
        "jsonOptions": {"prompt": "Extract the title"},
        "rejectRequestPattern": ["*.png"],
        "setJavaScriptEnabled": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"depth": 0}, "depth"),
        ({"formats": ["text"]}, "formats"),
        ({"crawl_purposes": ["advertising"]}, "crawl_purposes"),
        ({"max_age": 604_801}, "max_age"),
        ({"modified_since": int(time.time()) + 60}, "modified_since"),
        ({"include_patterns": [""]}, "includePatterns"),
        ({"json_options": []}, "json_options"),
        ({"render": False, "reject_request_patterns": ["*.png"]}, "render=True"),
    ],
)
async def test_crawl_rejects_invalid_current_contract(client, options, message):
    with pytest.raises(ValueError, match=message):
        await client.crawl("https://example.com", **options)


@pytest.mark.asyncio
async def test_crawl_status_returns_dict(client):
    payload = {"success": True, "result": {"id": "abc", "status": "running"}}
    with respx.mock:
        respx.get(f"{CF_BASE}/crawl/abc").mock(return_value=httpx.Response(200, json=payload))
        result = await client.crawl_status("abc")
    assert result["status"] == "running"


@pytest.mark.asyncio
async def test_crawl_status_rejects_malformed_normalized_fields(client):
    payload = {
        "success": True,
        "result": {"id": 123, "job_id": "wrong", "status": 456},
    }
    with respx.mock:
        respx.get(f"{CF_BASE}/crawl/abc").mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(CFBrowserError, match="malformed crawl status") as exc_info:
            await client.crawl_status("abc")
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_crawl_status_rejects_non_object_records(client):
    payload = {
        "success": True,
        "result": {"id": "abc", "status": "completed", "records": [None]},
    }
    with respx.mock:
        respx.get(f"{CF_BASE}/crawl/abc").mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(CFBrowserError, match="malformed crawl status") as exc_info:
            await client.crawl_status("abc")
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_crawl_status_forwards_pagination_filters(client):
    payload = {"success": True, "result": {"id": "abc", "status": "completed"}}
    with respx.mock:
        route = respx.get(f"{CF_BASE}/crawl/abc?cursor=opaque-next&limit=25&status=completed").mock(
            return_value=httpx.Response(200, json=payload)
        )
        await client.crawl_status("abc", cursor="opaque-next", limit=25, status="completed")
    assert route.called


@pytest.mark.asyncio
async def test_crawl_status_forwards_numeric_cursor(client):
    payload = {"success": True, "result": {"id": "abc", "status": "completed"}}
    with respx.mock:
        route = respx.get(f"{CF_BASE}/crawl/abc?cursor=10").mock(
            return_value=httpx.Response(200, json=payload)
        )
        await client.crawl_status("abc", cursor=10)
    assert route.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"cursor": ""}, "cursor must be a valid opaque cursor"),
        ({"cursor": True}, "cursor must be a valid opaque cursor"),
        ({"cursor": -1}, "cursor must be a valid opaque cursor"),
        ({"cursor": 9_007_199_254_740_992}, "cursor must be a valid opaque cursor"),
        ({"limit": True}, "limit must be an integer between"),
        ({"limit": 100_001}, "limit must be an integer between"),
        ({"status": "running"}, "Invalid crawl record status"),
    ],
)
async def test_crawl_status_rejects_invalid_filters(client, kwargs, message):
    with pytest.raises(ValueError, match=message):
        await client.crawl_status("abc", **kwargs)


@pytest.mark.asyncio
async def test_successful_invalid_json_raises_typed_error(client):
    with respx.mock:
        respx.get(f"{CF_BASE}/crawl/abc").mock(
            return_value=httpx.Response(
                200,
                text="not-json",
                headers={"Content-Type": "application/json"},
            )
        )
        with pytest.raises(CFBrowserError, match="invalid JSON"):
            await client.crawl_status("abc")


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
            200, json={"success": True, "result": {"id": "j1", "status": "completed"}}
        )

    with respx.mock:
        respx.get(f"{CF_BASE}/crawl/j1?limit=1").mock(side_effect=side_effect)
        respx.get(f"{CF_BASE}/crawl/j1", params={}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {"id": "j1", "status": "completed", "records": []},
                },
            )
        )
        result = await client.crawl_wait("j1", timeout=60, poll_interval=0.01)

    assert result["status"] == "completed"
    assert result["records"] == []
    assert call_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", ["next-page", 10])
async def test_crawl_wait_collects_all_cursor_pages(client, cursor):
    with respx.mock:
        respx.get(f"{CF_BASE}/crawl/j1?limit=1").mock(
            return_value=httpx.Response(
                200, json={"success": True, "result": {"id": "j1", "status": "completed"}}
            )
        )
        next_page = respx.get(f"{CF_BASE}/crawl/j1", params={"cursor": cursor}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {
                        "id": "j1",
                        "status": "completed",
                        "records": [{"url": "https://example.com/2"}],
                    },
                },
            )
        )
        respx.get(f"{CF_BASE}/crawl/j1", params={}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {
                        "id": "j1",
                        "status": "completed",
                        "records": [{"url": "https://example.com/1"}],
                        "cursor": cursor,
                    },
                },
            )
        )
        result = await client.crawl_wait("j1", timeout=60, poll_interval=0.01)

    assert [record["url"] for record in result["records"]] == [
        "https://example.com/1",
        "https://example.com/2",
    ]
    assert "cursor" not in result
    assert next_page.called


@pytest.mark.asyncio
async def test_crawl_wait_raises_on_timeout(client):
    with respx.mock:
        respx.get(f"{CF_BASE}/crawl/j1?limit=1").mock(
            return_value=httpx.Response(
                200, json={"success": True, "result": {"id": "j1", "status": "running"}}
            )
        )
        with pytest.raises(TimeoutError):
            await client.crawl_wait("j1", timeout=0.05, poll_interval=0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    ["errored", "cancelled_due_to_timeout", "cancelled_due_to_limits", "cancelled_by_user"],
)
async def test_crawl_wait_raises_on_current_terminal_failures(client, status):
    with respx.mock:
        respx.get(f"{CF_BASE}/crawl/j1?limit=1").mock(
            return_value=httpx.Response(
                200, json={"success": True, "result": {"id": "j1", "status": status}}
            )
        )
        with pytest.raises(CFBrowserError, match=status):
            await client.crawl_wait("j1", timeout=1, poll_interval=0.01)


@pytest.mark.asyncio
async def test_delete_crawl_uses_current_cancel_endpoint(client):
    with respx.mock:
        route = respx.delete(f"{CF_BASE}/crawl/job-abc").mock(
            return_value=httpx.Response(200, json={"job_id": "job-abc", "message": "cancelled"})
        )
        await client.delete_crawl("job-abc")
    assert route.called


@pytest.mark.asyncio
async def test_delete_crawl_rejects_http_200_unsuccessful_envelope(client):
    with respx.mock:
        respx.delete(f"{CF_BASE}/crawl/job-abc").mock(
            return_value=httpx.Response(
                200,
                json={"success": False, "errors": [{"message": "Cancellation failed"}]},
                headers={"Content-Type": "application/json"},
            )
        )
        with pytest.raises(CFBrowserError, match="Cancellation failed") as exc_info:
            await client.delete_crawl("job-abc")
    assert exc_info.value.status_code == 502


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
async def test_http_200_unsuccessful_envelope_raises_typed_error(client):
    with respx.mock:
        respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(
                200,
                json={"success": False, "errors": [{"message": "Rendering failed"}]},
                headers={"Content-Type": "application/json"},
            )
        )
        with pytest.raises(CFBrowserError, match="Rendering failed") as exc_info:
            await client.content("https://example.com")
    assert exc_info.value.status_code == 502


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
async def test_custom_headers_mapped_to_cf_api(client):
    """headers should be sent as setExtraHTTPHeaders to CF API."""
    custom_headers = {"X-Auth": "token123"}
    with respx.mock:
        route = respx.post(f"{CF_BASE}/markdown").mock(
            return_value=httpx.Response(200, text="# Hello")
        )
        await client.markdown("https://example.com", headers=custom_headers)
    sent = json.loads(route.calls[0].request.content)
    assert sent["setExtraHTTPHeaders"] == custom_headers
    assert "headers" not in sent


# ---------------------------------------------------------------------------
# Parameter mapping: wait_for → waitForSelector
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_maps_wait_for(client):
    """wait_for should be sent as waitForSelector to CF API."""
    with respx.mock:
        route = respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content("https://example.com", wait_for=".main")
    sent = json.loads(route.calls[0].request.content)
    assert sent["waitForSelector"] == {"selector": ".main"}
    assert "wait_for" not in sent


@pytest.mark.asyncio
async def test_screenshot_maps_wait_for(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/screenshot").mock(
            return_value=httpx.Response(200, content=b"\x89PNG")
        )
        await client.screenshot("https://example.com", wait_for="#app")
    sent = json.loads(route.calls[0].request.content)
    assert sent["waitForSelector"] == {"selector": "#app"}
    assert "wait_for" not in sent


@pytest.mark.asyncio
async def test_a11y_maps_wait_for(client):
    tree = {"role": "WebArea", "name": "Test"}
    with respx.mock:
        route = respx.post(f"{CF_BASE}/accessibilityTree").mock(
            return_value=httpx.Response(
                200,
                json={"success": True, "result": {"accessibilityTree": tree}},
            )
        )
        await client.a11y("https://example.com", wait_for="main")
    sent = json.loads(route.calls[0].request.content)
    assert sent["waitForSelector"] == {"selector": "main"}
    assert "wait_for" not in sent


# ---------------------------------------------------------------------------
# Parameter mapping: timeout → gotoOptions.timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_maps_timeout(client):
    """timeout should be sent as gotoOptions.timeout to CF API."""
    with respx.mock:
        route = respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content("https://example.com", timeout=5000)
    sent = json.loads(route.calls[0].request.content)
    assert sent["gotoOptions"]["timeout"] == 5000
    assert "timeout" not in sent


# ---------------------------------------------------------------------------
# Parameter mapping: wait_until → gotoOptions.waitUntil
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_maps_wait_until(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content("https://example.com", wait_until="networkidle0")
    sent = json.loads(route.calls[0].request.content)
    assert sent["gotoOptions"]["waitUntil"] == "networkidle0"
    assert "wait_until" not in sent


@pytest.mark.asyncio
async def test_timeout_and_wait_until_merge(client):
    """Both timeout and wait_until should merge into gotoOptions."""
    with respx.mock:
        route = respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content("https://example.com", timeout=3000, wait_until="networkidle2")
    sent = json.loads(route.calls[0].request.content)
    assert sent["gotoOptions"] == {"timeout": 3000, "waitUntil": "networkidle2"}


# ---------------------------------------------------------------------------
# Parameter mapping: user_agent → userAgent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_markdown_maps_user_agent(client):
    with respx.mock:
        route = respx.post(f"{CF_BASE}/markdown").mock(
            return_value=httpx.Response(200, text="# Hello")
        )
        await client.markdown("https://example.com", user_agent="MyBot/1.0")
    sent = json.loads(route.calls[0].request.content)
    assert sent["userAgent"] == "MyBot/1.0"
    assert "user_agent" not in sent


# ---------------------------------------------------------------------------
# Combined mapping: all params together
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_params_mapped_together(client):
    """All user-friendly params should map correctly when used together."""
    cookies = [{"name": "s", "value": "v"}]
    custom_headers = {"X-Auth": "tok"}
    with respx.mock:
        route = respx.post(f"{CF_BASE}/content").mock(
            return_value=httpx.Response(200, text="<html/>")
        )
        await client.content(
            "https://example.com",
            wait_for=".loaded",
            headers=custom_headers,
            cookies=cookies,
            timeout=10000,
            wait_until="networkidle0",
            user_agent="Bot/2.0",
        )
    sent = json.loads(route.calls[0].request.content)
    assert sent["waitForSelector"] == {"selector": ".loaded"}
    assert sent["setExtraHTTPHeaders"] == {"X-Auth": "tok"}
    assert sent["cookies"] == cookies
    assert sent["gotoOptions"] == {"timeout": 10000, "waitUntil": "networkidle0"}
    assert sent["userAgent"] == "Bot/2.0"
    # None of the snake_case originals should remain
    assert "wait_for" not in sent
    assert "headers" not in sent
    assert "timeout" not in sent
    assert "wait_until" not in sent
    assert "user_agent" not in sent


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_manager():
    with respx.mock:
        respx.post(f"{CF_BASE}/markdown").mock(return_value=httpx.Response(200, text="# Test"))
        async with CFBrowserDirect(account_id=ACCOUNT_ID, api_token=API_TOKEN) as browser:
            result = await browser.markdown("https://example.com")
    assert result == "# Test"


@pytest.mark.asyncio
async def test_context_manager_closes_client():
    browser = CFBrowserDirect(account_id=ACCOUNT_ID, api_token=API_TOKEN)
    async with browser:
        pass
    assert browser._client.is_closed
