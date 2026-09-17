"""The install command: config paths, merging, command choice. Never touches real config files."""

import json
from pathlib import Path
from typing import Any

import pytest

import install

GIT_URL = "git+https://github.com/bhandeland/monarch-money-mcp"


def on_path(name: str) -> str:
    return f"/on/path/{name}"


def nowhere(name: str) -> str | None:
    return None


@pytest.mark.parametrize("system, env, expected", [
    ("Darwin", {}, "home/Library/Application Support/Claude/claude_desktop_config.json"),
    ("Windows", {"APPDATA": "appdata"}, "appdata/Claude/claude_desktop_config.json"),
    ("Windows", {}, "home/AppData/Roaming/Claude/claude_desktop_config.json"),
    ("Linux", {}, "home/.config/Claude/claude_desktop_config.json"),
    ("Linux", {"XDG_CONFIG_HOME": "xdg"}, "xdg/Claude/claude_desktop_config.json"),
])
def test_desktop_config_path(system: str, env: dict[str, str], expected: str) -> None:
    assert install.desktop_config_path(system, env, Path("home")) == Path(expected)


def test_checkout_command_runs_uv_in_the_checkout(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "monarch-money-mcp"\n')
    command = install.server_command(tmp_path, lambda name: f"/bin/{name}")
    assert command == ["/bin/uv", "--directory", str(tmp_path), "run", "monarch-money-mcp"]


@pytest.mark.parametrize("pyproject", [None, '[project]\nname = "something-else"\n'])
def test_installed_command_runs_uvx_from_git(tmp_path: Path, pyproject: str | None) -> None:
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject)
    command = install.server_command(tmp_path, lambda name: f"/bin/{name}")
    assert command == ["/bin/uvx", "--from", GIT_URL, "monarch-money-mcp"]


def test_find_executable_prefers_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install.shutil, "which", on_path)
    assert install.find_executable("uv") == "/on/path/uv"


def test_find_executable_falls_back_to_install_locations(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uv = tmp_path / ".local" / "bin" / "uv"
    uv.parent.mkdir(parents=True)
    uv.touch()
    monkeypatch.setattr(install.shutil, "which", nowhere)
    monkeypatch.setattr(install.Path, "home", lambda: tmp_path)
    assert install.find_executable("uv") == str(uv)


def test_find_executable_gives_up_with_bare_name(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install.shutil, "which", nowhere)
    monkeypatch.setattr(install.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(install, "SYSTEM_BIN_DIRS", [])
    assert install.find_executable("uvx") == "uvx"


def test_snippet_has_no_credentials() -> None:
    assert install.snippet(["uvx", "x"]) == {
        "mcpServers": {"monarch-money": {"command": "uvx", "args": ["x"]}}}


def test_merge_creates_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    replaced = install.merge_config(path, ["/bin/uv", "run"])
    assert not replaced
    assert json.loads(path.read_text()) == {
        "mcpServers": {"monarch-money": {"command": "/bin/uv", "args": ["run"]}}}


def test_merge_keeps_other_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    existing: dict[str, Any] = {"theme": "dark", "mcpServers": {"other": {"command": "x"}}}
    path.write_text(json.dumps(existing))
    replaced = install.merge_config(path, ["/bin/uv"])
    assert not replaced
    assert json.loads(path.read_text()) == {
        "theme": "dark",
        "mcpServers": {"other": {"command": "x"},
                       "monarch-money": {"command": "/bin/uv", "args": []}}}


def test_merge_replaces_existing_entry(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mcpServers": {"monarch-money": {
        "command": "old", "env": {"MONARCH_PASSWORD": "secret"}}}}))
    replaced = install.merge_config(path, ["/bin/uv", "run"])
    assert replaced
    assert json.loads(path.read_text()) == {
        "mcpServers": {"monarch-money": {"command": "/bin/uv", "args": ["run"]}}}


def test_merge_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json")
    with pytest.raises(SystemExit, match="isn't valid JSON"):
        install.merge_config(path, ["/bin/uv"])
    assert path.read_text() == "{not json"


def test_install_desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                         capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr(install, "desktop_config_path", lambda: path)
    monkeypatch.setattr(install, "server_command", lambda: ["/bin/uv", "run"])
    install.install("claude-desktop")
    install.install("claude-desktop")
    out = capsys.readouterr().out
    assert f"Added monarch-money to {path}" in out
    assert f"Replaced the existing monarch-money entry in {path}" in out
    assert "Restart Claude Desktop" in out


def test_install_claude_code_runs_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []

    def run(args: list[str], check: bool) -> None:
        assert check
        ran.append(args)

    monkeypatch.setattr(install.shutil, "which", on_path)
    monkeypatch.setattr(install, "server_command", lambda: ["/bin/uv", "run"])
    monkeypatch.setattr(install.subprocess, "run", run)
    install.install("claude-code")
    assert ran == [["/on/path/claude", "mcp", "add", "--scope", "user", "monarch-money",
                    "--", "/bin/uv", "run"]]


def test_install_claude_code_prints_command_without_claude(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(install.shutil, "which", nowhere)
    monkeypatch.setattr(install, "server_command", lambda: ["/bin/uv", "run", "a b"])
    install.install("claude-code")
    out = capsys.readouterr().out
    assert "claude mcp add --scope user monarch-money -- /bin/uv run 'a b'" in out


def test_install_print(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(install, "server_command", lambda: ["/bin/uvx", "x"])
    install.install(None)
    assert json.loads(capsys.readouterr().out) == install.snippet(["/bin/uvx", "x"])
