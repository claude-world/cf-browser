#!/usr/bin/env python3
"""Ensure every distributable and runtime version source stays synchronized."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pyproject_version(path: Path) -> str:
    in_project = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        section = re.fullmatch(r"\[([^]]+)]", line)
        if section:
            in_project = section.group(1).strip() == "project"
            continue
        if in_project:
            match = re.fullmatch(r"version\s*=\s*[\"']([^\"']+)[\"']", line)
            if match:
                return match.group(1)
    raise ValueError(f"missing [project] version in {path}")


def regex_version(path: Path, pattern: str, label: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise ValueError(f"missing {label} version in {path}")
    return match.group(1)


def collect_versions(root: Path = ROOT) -> dict[str, str]:
    package_lock = json.loads((root / "worker" / "package-lock.json").read_text())
    return {
        "sdk": pyproject_version(root / "sdk" / "pyproject.toml"),
        "sdk-runtime": regex_version(
            root / "sdk" / "src" / "cf_browser" / "__init__.py",
            r'^__version__\s*=\s*["\']([^"\']+)["\']',
            "SDK runtime",
        ),
        "mcp-server": pyproject_version(root / "mcp-server" / "pyproject.toml"),
        "mcp-runtime": regex_version(
            root / "mcp-server" / "src" / "cf_browser_mcp" / "__init__.py",
            r'^__version__\s*=\s*["\']([^"\']+)["\']',
            "MCP runtime",
        ),
        "worker": str(
            json.loads((root / "worker" / "package.json").read_text())["version"]
        ),
        "worker-lock": str(package_lock["version"]),
        "worker-lock-root": str(package_lock["packages"][""]["version"]),
        "worker-health": regex_version(
            root / "worker" / "src" / "index.ts",
            r'^\s*version:\s*["\']([^"\']+)["\']',
            "Worker health",
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    versions = collect_versions()
    if len(set(versions.values())) != 1:
        raise SystemExit(f"component versions differ: {versions}")

    version = next(iter(versions.values()))
    if args.tag and args.tag != f"v{version}":
        raise SystemExit(f"release tag {args.tag!r} does not match v{version}")
    print(f"all component versions: {version}")


if __name__ == "__main__":
    main()
