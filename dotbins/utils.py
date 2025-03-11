"""Utility functions for dotbins."""

from __future__ import annotations

import functools
import logging
import os
import sys
from typing import TYPE_CHECKING

import requests
from rich.console import Console

if TYPE_CHECKING:
    from .config import DotbinsConfig

# Initialize rich console
console = Console()
logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging level based on verbosity."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


@functools.cache
def get_latest_release(repo: str) -> dict:
    """Get the latest release information from GitHub."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    log(f"Fetching latest release from {url}", "info", "🔍")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        log("Failed to fetch latest release.", "error", "❌")
        console.print_exception()
        msg = f"Failed to fetch latest release for {repo}: {e}"
        raise RuntimeError(msg) from e


def current_platform() -> tuple[str, str]:
    """Detect the current platform and architecture.

    Returns:
        Tuple containing (platform, architecture)
        platform: 'linux' or 'macos'
        architecture: 'amd64' or 'arm64'

    """
    # Detect platform
    platform = "linux"
    if sys.platform == "darwin":
        platform = "macos"

    # Detect architecture
    arch = "amd64"
    machine = os.uname().machine.lower()
    if machine in ["arm64", "aarch64"]:
        arch = "arm64"

    return platform, arch


def get_platform_map(platform: str, platform_map: dict) -> str:
    """Map dotbins platform names to tool-specific platform names.

    Args:
        platform: Platform name used by dotbins (e.g., 'macos')
        platform_map: Dictionary mapping platform names

    Returns:
        Mapped platform name

    """
    if not platform_map or not isinstance(platform_map, dict):
        return platform

    return platform_map.get(platform, platform)


def print_shell_setup(config: DotbinsConfig) -> None:
    """Print shell setup instructions."""
    tools_path = config.tools_dir.resolve()
    tools_dir = str(tools_path).replace(os.path.expanduser("~"), "$HOME")
    print("\n# Add this to your shell configuration file (e.g., .bashrc, .zshrc):")
    print(
        f"""
# dotbins - Add platform-specific binaries to PATH
_os=$(uname -s | tr '[:upper:]' '[:lower:]')
[[ "$_os" == "darwin" ]] && _os="macos"

_arch=$(uname -m)
[[ "$_arch" == "x86_64" ]] && _arch="amd64"
[[ "$_arch" == "aarch64" || "$_arch" == "arm64" ]] && _arch="arm64"

export PATH="{tools_dir}/$_os/$_arch/bin:$PATH"
""",
    )


def log(message: str, style: str = "default", emoji: str = "") -> None:
    """Print a formatted message to the console."""
    prefix = f"{emoji} " if emoji else ""
    if style == "error":
        console.print(f"{prefix}[bold red]{message}[/bold red]")
    elif style == "warning":
        console.print(f"{prefix}[yellow]{message}[/yellow]")
    elif style == "success":
        console.print(f"{prefix}[green]{message}[/green]")
    elif style == "info":
        console.print(f"{prefix}[blue]{message}[/blue]")
    else:
        console.print(f"{prefix}{message}")
