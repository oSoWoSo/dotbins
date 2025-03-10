"""dotbins - Dotfiles Binary Manager.

A utility for managing CLI tool binaries in your dotfiles repository.
Downloads and organizes binaries for popular tools across multiple
platforms (macOS, Linux) and architectures (amd64, arm64).

This tool helps maintain a consistent set of CLI utilities across all your
environments, with binaries tracked in your dotfiles git repository.
"""

from __future__ import annotations

__version__ = "0.1.0"

# Re-export commonly used functions
from . import analyze, cli, config, download, utils

__all__ = [
    "__version__",
    "analyze",
    "cli",
    "config",
    "download",
    "utils",
]
