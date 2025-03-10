"""Configuration management for dotbins."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

console = Console()


@dataclass
class DotbinsConfig:
    """Configuration for dotbins."""

    dotfiles_dir: Path = field(
        default_factory=lambda: Path(os.path.expanduser("~/.dotfiles")),
    )
    tools_dir: Path = field(
        default_factory=lambda: Path(os.path.expanduser("~/.dotfiles/tools")),
    )
    platforms: list[str] = field(default_factory=lambda: ["linux", "macos"])
    architectures: list[str] = field(default_factory=lambda: ["amd64", "arm64"])
    tools: dict[str, Any] = field(default_factory=dict)
    arch_maps: dict[str, dict[str, str]] = field(default_factory=dict)
    platform_maps: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load_from_file(cls, config_path: str | None = None) -> DotbinsConfig:
        """Load configuration from YAML file."""
        if not config_path:
            config_path = os.path.join(os.path.dirname(__file__), "..", "tools.yaml")

        try:
            with open(config_path) as file:
                config_data = yaml.safe_load(file)

            # Expand paths
            if isinstance(config_data.get("dotfiles_dir"), str):
                config_data["dotfiles_dir"] = Path(
                    os.path.expanduser(config_data["dotfiles_dir"]),
                )
            if isinstance(config_data.get("tools_dir"), str):
                config_data["tools_dir"] = Path(
                    os.path.expanduser(config_data["tools_dir"]),
                )

            return cls(**config_data)

        except Exception:  # noqa: BLE001
            console.print("❌ [bold red]Error loading configuration[/bold red]")
            console.print_exception()
            # Return default configuration
            return cls()
