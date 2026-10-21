#!/usr/bin/env python3
"""Verify Python release archives do not contain local state and expose typing."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def validate_members(members: list[str], archive: Path) -> None:
    for name in members:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"unsafe archive path in {archive}: {name}")
        if path.name == ".pymon":
            raise SystemExit(f"local .pymon state leaked into {archive}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("--require-py-typed", action="store_true")
    args = parser.parse_args()

    dist = args.package_dir / "dist"
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit(
            f"expected one wheel and one sdist in {dist}; "
            f"found {len(wheels)} wheel(s) and {len(sdists)} sdist(s)"
        )

    with zipfile.ZipFile(wheels[0]) as archive:
        wheel_members = archive.namelist()
    with tarfile.open(sdists[0], "r:gz") as archive:
        sdist_members = archive.getnames()
    validate_members(wheel_members, wheels[0])
    validate_members(sdist_members, sdists[0])

    if args.require_py_typed and not any(
        name.endswith("cf_browser/py.typed") for name in wheel_members
    ):
        raise SystemExit(f"PEP 561 marker missing from {wheels[0]}")

    print(f"verified {wheels[0].name} and {sdists[0].name}")


if __name__ == "__main__":
    main()
