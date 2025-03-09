"""Tests that download real GitHub releases for tools defined in tools.yaml."""

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

import pytest
import requests
import yaml

import dotbins


@pytest.fixture
def ensure_bin_dir():
    """Ensure the tests/bin directory exists."""
    bin_dir = Path(__file__).parent / "bin"
    bin_dir.mkdir(exist_ok=True)
    return bin_dir


@pytest.fixture
def tools_config():
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
) -> tuple[Optional[Path], Optional[dict[str, Any]]]:
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
        return None, release

    except requests.exceptions.RequestException as e:
        print(f"Error downloading {tool_name}: {e}")
        return None, None


def find_matching_asset(
    tool_config: dict[str, Any],
    release: dict[str, Any],
) -> Optional[dict[str, Any]]:
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


def analyze_tool_binary(
    tool_name: str,
    tool_config: dict[str, Any],
    tool_path: Path,
    release: Optional[dict[str, Any]] = None,
) -> None:
    """Extract and analyze a tool binary."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Extract archive
        try:
            dotbins.extract_archive(str(tool_path), str(temp_path))
        except Exception as e:
            print(f"Error extracting {tool_name}: {e}")
            return

        # Find executables
        executables = dotbins.find_executables(temp_path)
        if not executables:
            print(f"No executables found for {tool_name}")
            return

        print(f"Executables found for {tool_name}:")
        for exe in executables:
            print(f"  - {exe}")

        # Determine binary path
        binary_path = dotbins.determine_binary_path(executables, tool_name)
        if not binary_path:
            print(f"No binary path determined for {tool_name}")
            return

        print(f"Detected binary path for {tool_name}: {binary_path}")

        # Verify against expected configuration
        verify_binary_path(tool_name, tool_config, binary_path, release)

        # Test the binary
        test_binary_execution(tool_name, temp_path / binary_path)


def verify_binary_path(
    tool_name: str,
    tool_config: dict[str, Any],
    detected_path: str,
    release: Optional[dict[str, Any]] = None,
) -> None:
    """Verify the detected binary path against the expected configuration."""
    expected_path = tool_config.get("binary_path", "")
    if not expected_path:
        return

    # Replace variables in expected path
    version = release["tag_name"].lstrip("v") if release else ""
    if "{version}" in expected_path and version:
        expected_path = expected_path.replace("{version}", version)
    if "{arch}" in expected_path:
        expected_path = expected_path.replace("{arch}", "x86_64")

    # Remove globs for comparison
    expected_path = expected_path.replace("*", "")

    print(f"Expected binary path: {expected_path}")

    # TODO: Add actual assertion here if needed
    # We could check if the detected path matches the expected pattern


def test_binary_execution(tool_name: str, binary_path: Path) -> None:
    """Test if the binary can be executed."""
    if not binary_path.exists():
        print(f"Binary not found at {binary_path}")
        return

    try:
        binary_path.chmod(0o755)  # Make executable

        # Try with --help
        result = subprocess.run(
            [str(binary_path), "--help"],
            capture_output=True,
            timeout=5,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            print(f"Successfully executed {tool_name}")
            return

        # If --help failed, try --version
        result = subprocess.run(
            [str(binary_path), "--version"],
            capture_output=True,
            timeout=5,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            print(f"Successfully executed {tool_name} with --version")
            return

        print(f"Binary execution failed for {tool_name}")

    except subprocess.TimeoutExpired:
        print(f"Command timed out for {tool_name}")
    except Exception as e:
        print(f"Error running {tool_name}: {e}")


def test_analyze_real_tools(ensure_bin_dir: Path, tools_config: dict) -> None:
    """Test analyzing real tools from tools.yaml by downloading actual releases."""
    bin_dir = ensure_bin_dir

    for tool_name, tool_config in tools_config.items():
        print(f"\nTesting tool: {tool_name}")

        # Find and download asset
        tool_path, release = find_and_download_asset(tool_name, tool_config, bin_dir)

        if tool_path and tool_path.exists():
            # Analyze the tool binary
            analyze_tool_binary(tool_name, tool_config, tool_path, release)
