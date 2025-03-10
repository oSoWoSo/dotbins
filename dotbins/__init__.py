"""dotbins - Dotfiles Binary Manager.

A utility for managing CLI tool binaries in your dotfiles repository.
Downloads and organizes binaries for popular tools across multiple
platforms (macOS, Linux) and architectures (amd64, arm64).

This tool helps maintain a consistent set of CLI utilities across all your
environments, with binaries tracked in your dotfiles git repository.
"""

from __future__ import annotations

from . import analyze, cli, config, download, utils
from .cli import main

__version__ = "0.1.0"

# Re-export commonly used functions
from .analyze import analyze_tool, generate_tool_configuration
from .cli import initialize, list_tools, update_tools
from .config import load_config
from .download import download_tool, extract_from_archive, make_binaries_executable
from .utils import current_platform, get_latest_release, setup_logging

__all__ = [
    "analyze",
    "analyze_tool",
    "cli",
    "config",
    "current_platform",
    "download",
    "download_tool",
    "extract_from_archive",
    "generate_tool_configuration",
    "get_latest_release",
    "initialize",
    "list_tools",
    "load_config",
    "main",
    "make_binaries_executable",
    "setup_logging",
    "update_tools",
    "utils",
]
