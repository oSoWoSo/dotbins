"""Configuration management for dotbins."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import yaml

from .utils import log

DEFAULT_TOOLS_DIR = "~/.mydotbins/tools"
DEFAULT_PLATFORMS = {
    "linux": ["amd64", "arm64"],
    "macos": ["arm64"],
}

T = TypeVar("T")


@dataclass(frozen=True)
class ToolConfig:
    """Holds all config data for a single tool, without doing heavy logic."""

    tool_name: str
    repo: str
    binary_name: list[str] = field(default_factory=list)
    binary_path: list[str] = field(default_factory=list)
    extract_binary: bool = True
    asset_patterns: dict[str, dict[str, str]] = field(default_factory=dict)
    platform_map: dict[str, str] = field(default_factory=dict)
    arch_map: dict[str, str] = field(default_factory=dict)

    def tool_arch(self, arch: str) -> str:
        """Get the architecture for the tool."""
        return self.arch_map.get(arch, arch)

    def tool_platform(self, platform: str) -> str:
        """Get the platform for the tool."""
        return self.platform_map.get(platform, platform)


def build_tool_config(
    tool_name: str,
    raw_data: dict[str, Any],
    platforms: dict[str, list[str]] | None = None,
) -> ToolConfig:
    """Create a ToolConfig object from raw YAML data.

    Performing any expansions
    or normalization that used to happen inside the constructor.
    """
    if not platforms:
        platforms = DEFAULT_PLATFORMS

    # Safely grab data from raw_data (or set default if missing).
    repo = raw_data.get("repo") or ""
    extract_binary = raw_data.get("extract_binary", True)
    platform_map = raw_data.get("platform_map", {})
    arch_map = raw_data.get("arch_map", {})
    # Might be str or list
    raw_binary_name = raw_data.get("binary_name", tool_name)
    raw_binary_path = raw_data.get("binary_path", [])

    # Convert to lists
    binary_name: list[str] = _ensure_list(raw_binary_name)
    binary_path: list[str] = _ensure_list(raw_binary_path)

    # Normalize asset patterns to dict[platform][arch].
    raw_patterns = raw_data.get("asset_patterns")
    asset_patterns = _normalize_asset_patterns(raw_patterns, platforms)

    # Build our final data-class object
    return ToolConfig(
        tool_name=tool_name,
        repo=repo,
        binary_name=binary_name,
        binary_path=binary_path,
        extract_binary=extract_binary,
        asset_patterns=asset_patterns,
        platform_map=platform_map,
        arch_map=arch_map,
    )


def _ensure_list(value: T | list[T] | None) -> list[T]:
    """Convert a single value or None into a list, if not already a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_asset_patterns(
    patterns: str | dict[str, Any] | None,
    platforms: dict[str, list[str]],
) -> dict[str, dict[str, str]]:
    """Normalize the asset_patterns into a dict.

    Of the form:
    ```{ platform: { arch: pattern_str } }```.
    """
    # Start by initializing empty patterns for each platform/arch
    normalized: dict[str, dict[str, str]] = {
        platform: {arch: "?" for arch in arch_list}
        for platform, arch_list in platforms.items()
    }
    if not patterns:
        return normalized

    # If user gave a single string, apply it to all platform/arch combos
    if isinstance(patterns, str):
        for platform, arch_list in normalized.items():
            for arch in arch_list:
                normalized[platform][arch] = patterns
        return normalized

    # If user gave a dict, it might be "platform: pattern" or "platform: {arch: pattern}"
    if isinstance(patterns, dict):
        for platform, p_val in patterns.items():
            # Skip unknown platforms
            if platform not in normalized:
                continue

            # If p_val is a single string, apply to all arch
            if isinstance(p_val, str):
                for arch in normalized[platform]:
                    normalized[platform][arch] = p_val
            # Otherwise it might be {arch: pattern}
            elif isinstance(p_val, dict):
                for arch, pattern_str in p_val.items():
                    if arch in normalized[platform]:
                        normalized[platform][arch] = pattern_str
    return normalized


@dataclass
class Config:
    """Overall configuration for dotbins."""

    tools_dir: Path = field(default=Path(os.path.expanduser(DEFAULT_TOOLS_DIR)))
    platforms: dict[str, list[str]] = field(default_factory=lambda: DEFAULT_PLATFORMS)
    tools: dict[str, ToolConfig] = field(default_factory=dict)

    @property
    def platform_names(self) -> list[str]:
        """Return a list of platform names."""
        return list(self.platforms.keys())

    def get_architectures(self, platform: str) -> list[str]:
        """Return the list of architectures for a given platform."""
        return self.platforms.get(platform, [])

    def validate(self) -> None:
        """Check for missing repos, unknown platforms, etc."""
        for tool_name, tool_config in self.tools.items():
            self._validate_tool_config(tool_name, tool_config)

    def _validate_tool_config(
        self,
        tool_name: str,
        tool_config: ToolConfig,
    ) -> None:
        # Basic checks
        if not tool_config.repo:
            log(f"Tool {tool_name} is missing required field 'repo'", "error")

        # If no binary_path, we rely on auto-detection (just an info, not fatal):
        if not tool_config.binary_path:
            log(
                f"Tool {tool_name} has no binary_path specified - will attempt auto-detection",
                "info",
            )

        # If binary lists differ in length, log an error
        if (
            len(tool_config.binary_name) != len(tool_config.binary_path)
            and tool_config.binary_path
        ):
            log(
                f"Tool {tool_name}: 'binary_name' and 'binary_path' must have the same length if both are specified as lists.",
                "error",
            )

        # Check for unknown platforms/arch in asset_patterns
        for platform, pattern_map in tool_config.asset_patterns.items():
            if platform not in self.platforms:
                log(
                    f"Tool {tool_name}: 'asset_patterns' uses unknown platform '{platform}'",
                    "error",
                )
                continue

            for arch in pattern_map:
                if arch not in self.platforms[platform]:
                    log(
                        f"Tool {tool_name}: 'asset_patterns[{platform}]' uses unknown arch '{arch}'",
                        "error",
                    )

    @classmethod
    def load_from_file(cls, config_path: str | Path | None = None) -> Config:
        """Load configuration from YAML, or return defaults if no file found."""
        path = _find_config_file(config_path)
        if path is None:
            return cls()

        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            log(f"Configuration file not found: {path}", "warning")
            return cls()
        except yaml.YAMLError:
            log(
                f"Invalid YAML in configuration file: {path}",
                "error",
                print_exception=True,
            )
            return cls()

        # Build up the Config fields from the raw data
        tools_dir = data.get("tools_dir", DEFAULT_TOOLS_DIR)
        platforms = data.get("platforms", DEFAULT_PLATFORMS)
        raw_tools = data.get("tools", {})

        # Convert to Path
        tools_dir_path = Path(os.path.expanduser(tools_dir))

        # Build each ToolConfig
        tool_configs: dict[str, ToolConfig] = {}
        for tool_name, tool_data in raw_tools.items():
            tool_configs[tool_name] = build_tool_config(
                tool_name,
                tool_data,
                platforms,
            )

        config_obj = cls(
            tools_dir=tools_dir_path,
            platforms=platforms,
            tools=tool_configs,
        )
        config_obj.validate()
        return config_obj


def _find_config_file(config_path: str | Path | None) -> Path | None:
    """Look for the user-specified path or common defaults."""
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            log(f"Loading configuration from: {path}", "success")
            return path
        log(f"Config path provided but not found: {path}", "warning")
        return None

    home = Path.home()
    candidates = [
        Path.cwd() / "dotbins.yaml",
        home / ".config" / "dotbins" / "config.yaml",
        home / ".config" / "dotbins.yaml",
        home / ".dotbins.yaml",
        home / ".mydotbins" / "dotbins.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            log(f"Loading configuration from: {candidate}", "success")
            return candidate

    log("No configuration file found, using default settings", "warning")
    return None
