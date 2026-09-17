"""Sync manifest.json (the Claude Desktop extension) with the server.

Rewrites the manifest's version from pyproject.toml and its tool list from the
server's tool registry. tests/test_manifest.py fails when they drift.

    uv run python scripts/update_manifest.py
"""

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "manifest.json"
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


def summary(description: str) -> str:
    """The first sentence, which is what Claude Desktop has room to show."""
    first = description.split(". ", 1)[0].strip()
    return first if first.endswith(".") else first + "."


def expected_tools() -> list[dict[str, str]]:
    return [{"name": name, "description": summary(t.description or "")}
            for name, (t, _) in server.TOOLS.items()]


def project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text())


def main() -> None:
    manifest = load_manifest()
    manifest["version"] = project_version()
    manifest["tools"] = expected_tools()
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(manifest['tools'])} tools, version {manifest['version']}")


if __name__ == "__main__":
    main()
