"""Tests that analyze tools defined in tools.yaml and compare with existing configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests
import yaml

import dotbins


@pytest.fixture
def ensure_bin_dir() -> Path:
    """Ensure the tests/bin directory exists."""
    bin_dir = Path(__file__).parent / "bin"
    bin_dir.mkdir(exist_ok=True)
    return bin_dir


@pytest.fixture
def tools_config() -> dict[str, Any]:
    """Load tools configuration from tools.yaml."""
    script_dir = Path(__file__).parent.parent
    tools_yaml_path = script_dir / "tools.yaml"

    with open(tools_yaml_path) as f:
        config = yaml.safe_load(f)

    return config.get("tools", {})


def find_and_download_asset(
    tool_name: str,
    tool_config: dict[str, Any],
    bin_dir: Path,
) -> tuple[Path | None, dict[str, Any] | None]:
    """Find and download an appropriate asset for a tool.

    Returns
    -------
        Tuple containing the path to the downloaded asset and the release info (or None if failed)

    """
    tool_path = bin_dir / f"{tool_name}.tar.gz"

    # Skip if already downloaded
    if tool_path.exists():
        print(f"Using existing downloaded asset for {tool_name}")
        return tool_path, None

    repo = tool_config.get("repo")
    if not repo:
        print(f"Skipping {tool_name} - no repo defined")
        return None, None

    try:
        # Get latest release info
        release = dotbins.get_latest_release(repo)

        # Find an appropriate asset
        asset = find_matching_asset(tool_config, release)

        if asset:
            print(f"Downloading {asset['name']} for {tool_name}")
            dotbins.download_file(asset["browser_download_url"], str(tool_path))
            return tool_path, release
        print(f"No suitable asset found for {tool_name}")
        return None, release  # noqa: TRY300

    except requests.exceptions.RequestException as e:
        print(f"Error downloading {tool_name}: {e}")
        return None, None


def find_matching_asset(
    tool_config: dict[str, Any],
    release: dict[str, Any],
) -> dict[str, Any] | None:
    """Find an asset that matches the tool configuration."""
    asset = None
    version = release["tag_name"].lstrip("v")

    # Try asset_patterns first
    if "asset_patterns" in tool_config and "linux" in tool_config["asset_patterns"]:
        pattern = tool_config["asset_patterns"]["linux"]
        if pattern:
            search_pattern = pattern.format(
                version=version,
                platform="linux",
                arch="x86_64",
            )
            asset = dotbins.find_asset(release["assets"], search_pattern)

    # Try asset_pattern if patterns didn't work
    if not asset and "asset_pattern" in tool_config:
        pattern = tool_config["asset_pattern"]
        search_pattern = pattern.format(
            version=version,
            platform="linux",
            arch="x86_64",
        )
        asset = dotbins.find_asset(release["assets"], search_pattern)

    # Fallback to generic Linux asset
    if not asset:
        for a in release["assets"]:
            if (
                "linux" in a["name"].lower()
                and ("x86_64" in a["name"] or "amd64" in a["name"])
                and a["name"].endswith((".tar.gz", ".tgz", ".zip"))
            ):
                asset = a
                break

    return asset


def analyze_tool_with_dotbins(repo: str, tool_name: str) -> dict:
    """Run the analyze function and return the suggested configuration."""
    try:
        return dotbins.generate_tool_configuration(repo, tool_name)
    except Exception as e:  # noqa: BLE001
        print(f"Error analyzing {tool_name}: {e}")
        return {}


def compare_configs(existing: dict, suggested: dict) -> list[str]:
    """Compare existing and suggested configurations and return differences."""
    differences = []

    # Compare basic properties
    for key in ["repo", "extract_binary", "binary_name"]:
        if key in existing and key in suggested and existing[key] != suggested[key]:
            differences.append(  # noqa: PERF401
                f"{key}: existing='{existing[key]}', suggested='{suggested[key]}'",
            )

    # Compare binary_path (allowing for some variation)
    if "binary_path" in existing and "binary_path" in suggested:
        existing_path = existing["binary_path"]
        suggested_path = suggested["binary_path"]
        if existing_path != suggested_path:
            differences.append(
                f"binary_path: existing='{existing_path}', suggested='{suggested_path}'",
            )

    # Compare asset patterns (this is more complex due to different formats)
    if "asset_patterns" in existing and "asset_patterns" in suggested:
        for platform in ["linux", "macos"]:
            existing_pattern = existing["asset_patterns"].get(platform)
            suggested_pattern = suggested["asset_patterns"].get(platform)
            if existing_pattern != suggested_pattern:
                differences.append(
                    f"asset_patterns[{platform}]: existing='{existing_pattern}', "
                    f"suggested='{suggested_pattern}'",
                )
    elif "asset_pattern" in existing and "asset_pattern" in suggested:
        if existing["asset_pattern"] != suggested["asset_pattern"]:
            differences.append(
                f"asset_pattern: existing='{existing['asset_pattern']}', "
                f"suggested='{suggested['asset_pattern']}'",
            )
    elif "asset_pattern" in existing and "asset_patterns" in suggested:
        differences.append(
            "Config format different: existing uses asset_pattern, suggested uses asset_patterns",
        )
    elif "asset_patterns" in existing and "asset_pattern" in suggested:
        differences.append(
            "Config format different: existing uses asset_patterns, suggested uses asset_pattern",
        )

    return differences


def test_analyze_tools_against_config(ensure_bin_dir: Path, tools_config: dict) -> None:
    """Test analyzing tools and comparing results with existing configuration."""
    bin_dir = ensure_bin_dir

    for tool_name, existing_config in tools_config.items():
        print(f"\n=== Testing tool: {tool_name} ===")

        repo = existing_config.get("repo")
        if not repo:
            print(f"Skipping {tool_name} - no repo defined")
            continue

        # Download the asset (for cache purposes)
        find_and_download_asset(tool_name, existing_config, bin_dir)

        # Run analyze on the tool
        print(f"Running analyze on {repo}")
        suggested_config = analyze_tool_with_dotbins(repo, tool_name)

        if not suggested_config:
            print(f"No configuration generated for {tool_name}, skipping comparison")
            continue

        # Compare configurations
        print(f"Comparing configurations for {tool_name}")
        differences = compare_configs(existing_config, suggested_config)

        if differences:
            print("Differences found:")
            for diff in differences:
                print(f"  - {diff}")
        else:
            print("✅ No differences found - configurations match!")

        # Print detailed configurations for reference
        print("\nExisting configuration:")
        for key, value in existing_config.items():
            print(f"  {key}: {value}")

        print("\nSuggested configuration:")
        for key, value in suggested_config.items():
            print(f"  {key}: {value}")
