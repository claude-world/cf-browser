"""Regression tests for the cross-component release version gate."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_version_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "check_versions.py"
    spec = importlib.util.spec_from_file_location("check_versions", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_pypi_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "check_pypi_dependency.py"
    spec = importlib.util.spec_from_file_location("check_pypi_dependency", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(script.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def write_fixture(root: Path, versions: dict[str, str]) -> None:
    (root / "sdk/src/cf_browser").mkdir(parents=True)
    (root / "mcp-server/src/cf_browser_mcp").mkdir(parents=True)
    (root / "worker/src").mkdir(parents=True)
    (root / "sdk/pyproject.toml").write_text(
        f'[project]\nversion = "{versions["sdk"]}"\n', encoding="utf-8"
    )
    (root / "sdk/src/cf_browser/__init__.py").write_text(
        f'__version__ = "{versions["sdk-runtime"]}"\n', encoding="utf-8"
    )
    (root / "mcp-server/pyproject.toml").write_text(
        f'[project]\nversion = "{versions["mcp-server"]}"\n', encoding="utf-8"
    )
    (root / "mcp-server/src/cf_browser_mcp/__init__.py").write_text(
        f'__version__ = "{versions["mcp-runtime"]}"\n', encoding="utf-8"
    )
    (root / "worker/package.json").write_text(
        json.dumps({"version": versions["worker"]}), encoding="utf-8"
    )
    (root / "worker/package-lock.json").write_text(
        json.dumps(
            {
                "version": versions["worker-lock"],
                "packages": {"": {"version": versions["worker-lock-root"]}},
            }
        ),
        encoding="utf-8",
    )
    (root / "worker/src/index.ts").write_text(
        f'  version: "{versions["worker-health"]}",\n', encoding="utf-8"
    )


def test_collect_versions_catches_every_runtime_source(tmp_path):
    module = load_version_module()
    versions = {
        "sdk": "2.1.0",
        "sdk-runtime": "2.1.0",
        "mcp-server": "2.1.0",
        "mcp-runtime": "2.1.0",
        "worker": "2.1.0",
        "worker-lock": "2.1.0",
        "worker-lock-root": "2.1.0",
        "worker-health": "2.1.1",
    }
    write_fixture(tmp_path, versions)

    collected = module.collect_versions(tmp_path)

    assert collected == versions
    assert len(set(collected.values())) == 2


def test_pypi_release_parser_requires_a_non_yanked_installable_file():
    module = load_pypi_module()
    payload = {
        "releases": {
            "2.0.0": [],
            "2.0.1": [
                {
                    "packagetype": "bdist_wheel",
                    "url": "https://files.pythonhosted.org/yanked.whl",
                    "yanked": True,
                }
            ],
            "2.0.2": [
                {
                    "packagetype": "bdist_egg",
                    "url": "https://files.pythonhosted.org/legacy.egg",
                    "yanked": False,
                }
            ],
            "2.1.0": [
                {
                    "packagetype": "bdist_wheel",
                    "url": "https://files.pythonhosted.org/cf_browser-2.1.0.whl",
                    "yanked": False,
                }
            ],
            "2.1.1": [
                {
                    "packagetype": "sdist",
                    "url": "https://files.pythonhosted.org/cf_browser-2.1.1.tar.gz",
                }
            ],
        }
    }

    assert module.published_versions(payload) == {"2.1.0", "2.1.1"}
