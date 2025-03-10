"""Utility functions for dotbins."""

from __future__ import annotations

import os
import sys

import requests
from rich.console import Console

# Initialize rich console
console = Console()


def setup_logging(verbose: bool = False) -> None:  # noqa: FBT001, FBT002
    """Configure logging level based on verbosity."""
    # No need to configure standard logging as we're using rich


def get_latest_release(repo: str) -> dict:
    """Get the latest release information from GitHub."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    console.print(f"🔍 [blue]Fetching latest release from {url}[/blue]")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def current_platform() -> tuple:
    """Detect the current platform and architecture."""
    platform = "linux"
    if sys.platform == "darwin":
        platform = "macos"

    arch = "amd64"
    machine = os.uname().machine.lower()
    if machine in ["arm64", "aarch64"]:
        arch = "arm64"

    return platform, arch


def print_shell_setup() -> None:
    """Print shell setup instructions."""
    print("\n# Add this to your shell configuration file (e.g., .bashrc, .zshrc):")
    print(
        """
# dotbins - Add platform-specific binaries to PATH
_os=$(uname -s | tr '[:upper:]' '[:lower:]')
[[ "$_os" == "darwin" ]] && _os="macos"

_arch=$(uname -m)
[[ "$_arch" == "x86_64" ]] && _arch="amd64"
[[ "$_arch" == "aarch64" || "$_arch" == "arm64" ]] && _arch="arm64"

export PATH="$HOME/.dotfiles/tools/$_os/$_arch/bin:$PATH"
""",
    )
