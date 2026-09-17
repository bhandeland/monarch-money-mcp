"""manifest.json (the Claude Desktop extension) must match the server."""

import re

from scripts import update_manifest

FIX = "run `uv run python scripts/update_manifest.py`"


def test_manifest_tools_match_registry() -> None:
    manifest = update_manifest.load_manifest()
    assert manifest["tools"] == update_manifest.expected_tools(), FIX


def test_manifest_version_matches_pyproject() -> None:
    assert update_manifest.load_manifest()["version"] == update_manifest.project_version(), FIX


def test_manifest_env_uses_declared_settings() -> None:
    manifest = update_manifest.load_manifest()
    env: dict[str, str] = manifest["server"]["mcp_config"]["env"]
    used = {m for v in env.values() for m in re.findall(r"\$\{user_config\.([^}]+)\}", v)}
    assert used == set(manifest["user_config"])
    assert all(not option.get("required") for option in manifest["user_config"].values())


def test_summary_keeps_first_sentence() -> None:
    assert update_manifest.summary("Get things. Then more.") == "Get things."
    assert update_manifest.summary("No period") == "No period."
