#!/usr/bin/env python3
"""Fail an MCP-only release unless its exact SDK version is already on PyPI."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from check_versions import ROOT, collect_versions

PYPI_JSON_URL = "https://pypi.org/pypi/cf-browser/json"


def published_versions(payload: object) -> set[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("releases"), dict):
        raise ValueError("PyPI returned an unexpected package response")
    installable_types = {"bdist_wheel", "sdist"}
    return {
        str(version)
        for version, files in payload["releases"].items()
        if isinstance(files, list)
        and any(
            isinstance(file, dict)
            and file.get("yanked") is not True
            and file.get("packagetype") in installable_types
            and isinstance(file.get("url"), str)
            and bool(file["url"])
            for file in files
        )
    }


def main() -> None:
    versions = collect_versions()
    sdk_version = versions["sdk"]
    mcp_project = (ROOT / "mcp-server" / "pyproject.toml").read_text(encoding="utf-8")
    expected_floor = f"cf-browser>={sdk_version},<3"
    if expected_floor not in mcp_project:
        raise SystemExit(
            f"MCP dependency must include {expected_floor!r} before an MCP-only release"
        )

    request = Request(
        PYPI_JSON_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "cf-browser-release-gate/1",
        },
    )
    try:
        # The URL is a fixed module constant; no caller-controlled scheme or path reaches urllib.
        with urlopen(  # nosemgrep: dynamic-urllib-use-detected
            request, timeout=15
        ) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise SystemExit(f"Unable to verify cf-browser on PyPI: {exc}") from exc

    if sdk_version not in published_versions(payload):
        raise SystemExit(
            f"cf-browser {sdk_version} is not on PyPI; publish the SDK before the MCP server"
        )
    print(f"cf-browser {sdk_version} is available on PyPI")


if __name__ == "__main__":
    main()
