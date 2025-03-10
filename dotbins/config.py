"""Configuration management for dotbins."""

from __future__ import annotations

import os
import os.path
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

# Initialize rich console
console = Console()


# Function to load the configuration
def load_config() -> dict[str, Any]:
    """Load configuration from YAML file."""
    config_path = os.path.join(os.path.dirname(__file__), "..", "tools.yaml")
    try:
        with open(config_path) as file:
            config = yaml.safe_load(file)

        # Convert home directory shorthand
        if isinstance(config.get("dotfiles_dir"), str):
            config["dotfiles_dir"] = os.path.expanduser(config["dotfiles_dir"])
        if isinstance(config.get("tools_dir"), str):
            config["tools_dir"] = os.path.expanduser(config["tools_dir"])
    except Exception:  # noqa: BLE001
        console.print("❌ [bold red]Error loading configuration[/bold red]")
        console.print_exception()
        # Fallback to defaults
        return {
            "dotfiles_dir": os.path.expanduser("~/.dotfiles"),
            "tools_dir": os.path.expanduser("~/.dotfiles/tools"),
            "platforms": ["linux", "macos"],
            "architectures": ["amd64", "arm64"],
            "tools": {},
        }
    else:
        return config


# Load configuration
CONFIG = load_config()
DOTFILES_DIR = Path(CONFIG.get("dotfiles_dir", "~/.dotfiles"))
TOOLS_DIR = Path(CONFIG.get("tools_dir", "~/.dotfiles/tools"))
PLATFORMS = CONFIG.get("platforms", ["linux", "macos"])
ARCHITECTURES = CONFIG.get("architectures", ["amd64", "arm64"])
TOOLS = CONFIG.get("tools", {})
