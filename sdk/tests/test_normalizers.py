"""Fail-closed response normalizer regression tests."""

from __future__ import annotations

import pytest

from cf_browser._normalizers import normalize_links_response, normalize_scrape_response
from cf_browser.exceptions import CFBrowserError


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"elements": "not-a-list"},
        {"elements": [123]},
        [None],
        "wrong",
    ],
)
def test_scrape_normalizer_rejects_malformed_payload(payload):
    with pytest.raises(CFBrowserError, match="malformed scrape response") as exc_info:
        normalize_scrape_response(payload)
    assert exc_info.value.status_code == 502


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"links": "not-a-list"},
        [123],
        [{"href": "https://example.com", "text": 123}],
    ],
)
def test_links_normalizer_rejects_malformed_payload(payload):
    with pytest.raises(CFBrowserError, match="malformed links response") as exc_info:
        normalize_links_response(payload)
    assert exc_info.value.status_code == 502


def test_normalizers_keep_supported_response_variants():
    assert normalize_scrape_response([{"selector": "h1"}]) == {"elements": [{"selector": "h1"}]}
    assert normalize_links_response(
        {
            "links": [
                "https://example.com",
                {"href": "https://example.com/about", "text": "About"},
                {"href": "https://example.com/contact", "text": None},
            ]
        }
    ) == [
        {"href": "https://example.com", "text": None},
        {"href": "https://example.com/about", "text": "About"},
        {"href": "https://example.com/contact", "text": None},
    ]
