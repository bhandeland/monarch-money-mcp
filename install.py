"""Add the server to MCP client configs (Claude Desktop, Claude Code, or any other client)."""

import json
import os
import platform
import shlex
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

SERVER_NAME = "monarch-money"
PACKAGE = "monarch-money-mcp"
GIT_URL = "git+https://github.com/bhandeland/monarch-money-mcp"

# Where uv's installers put uv/uvx, relative to the home directory. GUI apps don't
# inherit the shell's PATH, so the config gets an absolute path.
HOME_BIN_DIRS = [".local/bin", ".cargo/bin"]
SYSTEM_BIN_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]


def desktop_config_path(system: str | None = None, env: Mapping[str, str] | None = None,
                        home: Path | None = None) -> Path:
    """Claude Desktop's config file for this OS."""
    system = system or platform.system()
    env = os.environ if env is None else env
    home = home or Path.home()
    if system == "Darwin":
        base = home / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(env["APPDATA"]) if env.get("APPDATA") else home / "AppData" / "Roaming"
    else:
        base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else home / ".config"
    return base / "Claude" / "claude_desktop_config.json"


def find_executable(name: str) -> str:
    """Absolute path to uv or uvx, or the bare name if it can't be found."""
    found = shutil.which(name)
    if found:
        return found
    home = Path.home()
    candidates = [home / d for d in HOME_BIN_DIRS] + [Path(d) for d in SYSTEM_BIN_DIRS]
    for directory in candidates:
        for filename in (name, f"{name}.exe"):
            if (directory / filename).is_file():
                return str(directory / filename)
    return name


def server_command(package_dir: Path | None = None,
                   find: Callable[[str], str] = find_executable) -> list[str]:
    """The command that starts the server.

    From a source checkout, run that checkout; otherwise run the latest version from git.
    """
    package_dir = package_dir or Path(__file__).resolve().parent
    pyproject = package_dir / "pyproject.toml"
    if pyproject.is_file() and f'name = "{PACKAGE}"' in pyproject.read_text():
        return [find("uv"), "--directory", str(package_dir), "run", PACKAGE]
    return [find("uvx"), "--from", GIT_URL, PACKAGE]


def snippet(command: list[str]) -> dict[str, Any]:
    """An mcpServers block for the command. Never includes credentials."""
    return {"mcpServers": {SERVER_NAME: {"command": command[0], "args": command[1:]}}}


def merge_config(path: Path, command: list[str]) -> bool:
    """Add or replace the server's entry in a JSON config. Returns whether it replaced one."""
    config: dict[str, Any] = {}
    if path.exists():
        try:
            config = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path} isn't valid JSON ({e}); fix or move it and try again")
    servers: dict[str, Any] = config.setdefault("mcpServers", {})
    replaced = SERVER_NAME in servers
    servers[SERVER_NAME] = snippet(command)["mcpServers"][SERVER_NAME]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
    return replaced


def join_command(args: list[str]) -> str:
    if platform.system() == "Windows":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


def install(client: str | None) -> None:
    """Install into Claude Desktop or Claude Code, or print the config for anything else."""
    command = server_command()
    if client == "claude-desktop":
        path = desktop_config_path()
        if merge_config(path, command):
            print(f"Replaced the existing {SERVER_NAME} entry in {path}")
        else:
            print(f"Added {SERVER_NAME} to {path}")
        print("Restart Claude Desktop to load it.")
    elif client == "claude-code":
        add = ["mcp", "add", "--scope", "user", SERVER_NAME, "--", *command]
        claude = shutil.which("claude")
        if claude:
            subprocess.run([claude, *add], check=True)
        else:
            print("The claude command isn't on your PATH. Run this to add the server:")
            print(join_command(["claude", *add]))
    else:
        print(json.dumps(snippet(command), indent=2))
