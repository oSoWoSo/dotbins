#!/usr/bin/env python3
"""dotbins - Dotfiles Binary Manager.

A utility for managing CLI tool binaries in your dotfiles repository.
Downloads and organizes binaries for popular tools across multiple
platforms (macOS, Linux) and architectures (amd64, arm64).

This tool helps maintain a consistent set of CLI utilities across all your
environments, with binaries tracked in your dotfiles git repository.
"""

from __future__ import annotations

import argparse
import os
import os.path
import re
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import requests
import yaml
from rich.console import Console

# Initialize rich console
console = Console()


# Function to load the configuration
def load_config() -> dict[str, Any]:
    """Load configuration from YAML file."""
    config_path = os.path.join(os.path.dirname(__file__), "tools.yaml")
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


def find_asset(assets: list[dict], pattern: str) -> dict | None:
    """Find an asset that matches the given pattern."""
    regex_pattern = (
        pattern.replace("{version}", ".*")
        .replace("{arch}", ".*")
        .replace("{platform}", ".*")
    )
    console.print(f"🔍 [blue]Looking for asset with pattern: {regex_pattern}[/blue]")

    for asset in assets:
        if re.search(regex_pattern, asset["name"]):
            console.print(f"✅ [green]Found matching asset: {asset['name']}[/green]")
            return asset

    return None


def download_file(url: str, destination: str) -> str:
    """Download a file from a URL to a destination path."""
    console.print(f"📥 [blue]Downloading from {url}[/blue]")
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()

    with open(destination, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    return destination


def extract_from_archive(  # noqa: PLR0912, PLR0915
    archive_path: str,
    destination_dir: Path,
    tool_config: dict,
    platform: str,  # noqa: ARG001
) -> None:
    """Extract a binary from an archive using explicit paths."""
    console.print(f"📦 [blue]Extracting from {archive_path}[/blue]")
    temp_dir = Path(tempfile.mkdtemp())

    # Check for gzip file types
    is_tarball = False
    try:
        with open(archive_path, "rb") as f:
            # Check for gzip magic number (1f 8b)
            if f.read(2) == b"\x1f\x8b":
                is_tarball = True
    except Exception:  # noqa: BLE001
        console.print("❌ [bold red]Error checking file type[/bold red]")
        console.print_exception()

    # Extract based on file type
    try:
        if is_tarball or archive_path.endswith((".tar.gz", ".tgz")):
            console.print("📦 [blue]Processing as tar.gz archive[/blue]")
            with tarfile.open(archive_path, mode="r:gz") as tar:
                tar.extractall(path=temp_dir)
        elif archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zip_file:
                zip_file.extractall(path=temp_dir)
        else:
            console.print(f"⚠️ [yellow]Unknown archive type: {archive_path}[/yellow]")
            msg = f"Cannot extract archive: {archive_path}"
            raise ValueError(msg)  # noqa: TRY301
    except Exception:
        console.print("❌ [bold red]Extraction failed[/bold red]")
        console.print_exception()
        shutil.rmtree(temp_dir)
        raise

    console.print(f"📦 [green]Archive extracted to {temp_dir}[/green]")

    # Debug: List the top-level files
    try:
        console.print("📋 [blue]Extracted files:[/blue]")
        for item in temp_dir.glob("**/*"):
            console.print(f"  - {item.relative_to(temp_dir)}")
    except Exception:  # noqa: BLE001
        console.print("⚠️ [yellow]Could not list extracted files[/yellow]")

    try:
        # Get the binary path from configuration
        binary_path = tool_config.get("binary_path")
        if not binary_path:
            msg = "No binary path specified in configuration"
            raise ValueError(msg)

        # Replace variables in the binary path
        if "{version}" in binary_path:
            version = tool_config.get("version", "")
            binary_path = binary_path.replace("{version}", version)

        if "{arch}" in binary_path:
            arch = tool_config.get("arch", "")
            binary_path = binary_path.replace("{arch}", arch)

        # Handle glob patterns in binary path
        if "*" in binary_path:
            matches = list(temp_dir.glob(binary_path))
            if not matches:
                msg = f"No files matching {binary_path} in archive"
                raise FileNotFoundError(msg)
            source_path = matches[0]
        else:
            source_path = temp_dir / binary_path
            if not source_path.exists():
                found = list(temp_dir.glob("**"))
                msg = f"Binary not found at {source_path}, found: {found}"
                raise FileNotFoundError(msg)

        # Create the destination directory if needed
        destination_dir.mkdir(parents=True, exist_ok=True)

        # Determine destination filename
        binary_name = tool_config.get("binary_name", source_path.name)
        dest_path = destination_dir / binary_name

        # Copy the binary and set permissions
        shutil.copy2(source_path, dest_path)
        dest_path.chmod(dest_path.stat().st_mode | 0o755)
        console.print(f"✅ [green]Copied binary to {dest_path}[/green]")

    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir)


def download_tool(  # noqa: PLR0912, PLR0915
    tool_name: str,
    platform: str,
    arch: str,
    force: bool = False,  # noqa: FBT001, FBT002
) -> bool:
    """Download a tool for a specific platform and architecture."""
    tool_config = TOOLS.get(tool_name)
    if not tool_config:
        console.print(
            f"❌ [bold red]Tool '{tool_name}' not found in configuration[/bold red]",
        )
        return False

    destination_dir = TOOLS_DIR / platform / arch / "bin"
    destination_dir.mkdir(parents=True, exist_ok=True)

    # Check if we should skip this download
    binary_name = tool_config.get("binary_name", tool_name)
    binary_path = destination_dir / binary_name

    if binary_path.exists() and not force:
        console.print(
            f"✅ [green]{tool_name} for {platform}/{arch} already exists (use --force to update)[/green]",
        )
        return True

    try:
        # Get latest release info
        repo = tool_config.get("repo")
        release = get_latest_release(repo)
        version = release["tag_name"].lstrip("v")
        tool_config["version"] = version  # Store for later use

        # Map architecture if needed
        tool_arch = arch
        # First check global arch_maps
        arch_maps = CONFIG.get("arch_maps", {}).get(tool_name, {})
        if arch in arch_maps:
            tool_arch = arch_maps[arch]
        # Then check tool-specific arch_map (this has priority)
        tool_arch_map = tool_config.get("arch_map", {})
        if arch in tool_arch_map:
            tool_arch = tool_arch_map[arch]
        tool_config["arch"] = tool_arch  # Store for later use

        # Map platform if needed
        tool_platform = platform
        platform_map = tool_config.get("platform_map", "")
        if platform_map:
            for platform_pair in platform_map.split(","):
                src, dst = platform_pair.split(":")
                if platform == src:
                    tool_platform = dst
                    break

        # Determine asset pattern
        if "asset_patterns" in tool_config:
            asset_pattern = tool_config["asset_patterns"].get(platform)
            if asset_pattern is None:
                console.print(
                    f"⚠️ [yellow]No asset pattern defined for {tool_name} on {platform}[/yellow]",
                )
                return False
        else:
            asset_pattern = tool_config.get("asset_pattern")

        # Replace variables in pattern
        search_pattern = asset_pattern.format(
            version=version,
            platform=tool_platform,
            arch=tool_arch,
        )

        # Find matching asset
        asset = find_asset(release["assets"], search_pattern)
        if not asset:
            console.print(
                f"⚠️ [yellow]No asset matching '{search_pattern}' found for {tool_name}[/yellow]",
            )
            return False

        # Download the asset
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=os.path.splitext(asset["name"])[1],
        ) as temp_file:
            temp_path = temp_file.name

        try:
            download_file(asset["browser_download_url"], temp_path)

            if tool_config.get("extract_binary", False):
                # Extract the binary using the explicit path
                extract_from_archive(temp_path, destination_dir, tool_config, platform)
            else:
                # Just copy the file directly
                shutil.copy2(temp_path, destination_dir / binary_name)
                # Make executable
                dest_file = destination_dir / binary_name
                dest_file.chmod(dest_file.stat().st_mode | 0o755)

            console.print(
                f"✅ [green]Successfully downloaded {tool_name} for {platform}/{arch}[/green]",
            )
            return True

        finally:
            # Cleanup
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    except Exception:  # noqa: BLE001
        console.print(
            f"❌ [bold red]Error processing {tool_name} for {platform}/{arch}[/bold red]",
        )
        console.print_exception()
        return False


def make_binaries_executable() -> None:
    """Make all binaries executable."""
    for platform in PLATFORMS:
        for arch in ARCHITECTURES:
            bin_dir = TOOLS_DIR / platform / arch / "bin"
            if bin_dir.exists():
                for binary in bin_dir.iterdir():
                    if binary.is_file():
                        binary.chmod(binary.stat().st_mode | 0o755)


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


def list_tools(_args: Any) -> None:
    """List available tools."""
    console.print("🔧 [blue]Available tools:[/blue]")
    for tool, config in TOOLS.items():
        console.print(f"  [green]{tool}[/green] (from {config['repo']})")


def update_tools(args: argparse.Namespace) -> None:
    """Update tools based on command line arguments."""
    tools_to_update = args.tools if args.tools else TOOLS.keys()
    platforms_to_update = [args.platform] if args.platform else PLATFORMS
    archs_to_update = [args.architecture] if args.architecture else ARCHITECTURES

    # Validate tools
    for tool in tools_to_update:
        if tool not in TOOLS:
            console.print(f"❌ [bold red]Unknown tool: {tool}[/bold red]")
            sys.exit(1)

    # Create the tools directory structure
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)

    success_count = 0
    total_count = 0

    for tool_name in tools_to_update:
        for platform in platforms_to_update:
            for arch in archs_to_update:
                total_count += 1
                if download_tool(tool_name, platform, arch, args.force):
                    success_count += 1

    make_binaries_executable()

    console.print(
        f"\n🔄 [blue]Completed: {success_count}/{total_count} tools updated successfully[/blue]",
    )

    if success_count > 0:
        console.print(
            "💾 [green]Don't forget to commit the changes to your dotfiles repository[/green]",
        )

    if args.shell_setup:
        print_shell_setup()


def initialize(_args: Any) -> None:
    """Initialize the tools directory structure."""
    for platform in PLATFORMS:
        for arch in ARCHITECTURES:
            (TOOLS_DIR / platform / arch / "bin").mkdir(parents=True, exist_ok=True)

    console.print("🛠️ [green]Initialized tools directory structure[/green]")
    print_shell_setup()


def generate_tool_configuration(
    repo: str,
    tool_name: str | None = None,
    release: dict | None = None,
) -> dict:
    """Analyze GitHub releases and generate tool configuration.

    This is the core functionality of the analyze_tool command,
    without the output formatting.

    Parameters
    ----------
    repo : str
        GitHub repository in the format 'owner/repo'
    tool_name : str, optional
        Name to use for the tool. If None, uses repo name
    release : dict, optional
        Pre-fetched release data. If None, it will be fetched from GitHub

    Returns
    -------
    dict
        Tool configuration dictionary

    """
    if not repo or "/" not in repo:
        msg = "Please provide a valid GitHub repository in the format 'owner/repo'"
        raise ValueError(msg)

    # Extract tool name from repo if not provided
    if not tool_name:
        tool_name = repo.split("/")[-1]

    # Get latest release info if not provided
    if release is None:
        release = get_latest_release(repo)

    # Find sample asset and determine binary path
    sample_asset = find_sample_asset(release["assets"])
    binary_path = None

    if sample_asset:
        binary_path = download_and_find_binary(sample_asset, tool_name)

    # Generate and return tool configuration
    return generate_tool_config(repo, tool_name, release, binary_path)


def analyze_tool(args: argparse.Namespace) -> None:
    """Analyze GitHub releases for a tool to help determine patterns."""
    repo = args.repo

    try:
        console.print(f"🔍 [blue]Analyzing releases for {repo}...[/blue]")
        release = get_latest_release(repo)

        console.print(
            f"\n🏷️ [green]Latest release: {release['tag_name']} ({release['name']})[/green]",
        )
        print_assets_info(release["assets"])

        # Extract tool name from repo or use provided name
        tool_name = args.name or repo.split("/")[-1]

        # Generate tool configuration using the refactored function
        # Pass the already fetched release to avoid duplicate API calls
        tool_config = generate_tool_configuration(repo, tool_name, release)

        # Output YAML
        console.print("\n📋 [blue]Suggested configuration for YAML tools file:[/blue]")
        yaml_config = {tool_name: tool_config}
        print(yaml.dump(yaml_config, sort_keys=False, default_flow_style=False))

    except Exception as e:  # noqa: BLE001
        console.print("❌ [bold red]Error analyzing repo[/bold red]")
        console.print_exception()
        console.print(f"❌ [bold red]Error: {e!s}[/bold red]")
        sys.exit(1)


def print_assets_info(assets: list[dict]) -> None:
    """Print detailed information about available assets."""
    console.print("\n📦 [blue]Available assets:[/blue]")
    for asset in assets:
        console.print(f"  - {asset['name']} ({asset['browser_download_url']})")

    # Platform categorization
    linux_assets = get_platform_assets(assets, "linux")
    console.print("\n🐧 [blue]Linux assets:[/blue]")
    for asset in linux_assets:
        console.print(f"  - {asset['name']}")

    macos_assets = get_platform_assets(assets, "macos")
    console.print("\n🍏 [blue]macOS assets:[/blue]")
    for asset in macos_assets:
        console.print(f"  - {asset['name']}")

    # Architecture categorization
    amd64_assets = get_arch_assets(assets, "amd64")
    console.print("\n💻 [blue]AMD64/x86_64 assets:[/blue]")
    for asset in amd64_assets:
        console.print(f"  - {asset['name']}")

    arm64_assets = get_arch_assets(assets, "arm64")
    console.print("\n📱 [blue]ARM64/aarch64 assets:[/blue]")
    for asset in arm64_assets:
        console.print(f"  - {asset['name']}")


def get_platform_assets(assets: list[dict], platform: str) -> list[dict]:
    """Filter assets by platform."""
    if platform == "linux":
        return [a for a in assets if "linux" in a["name"].lower()]
    if platform == "macos":
        return [
            a
            for a in assets
            if "darwin" in a["name"].lower() or "macos" in a["name"].lower()
        ]
    return []


def get_arch_assets(assets: list[dict], arch: str) -> list[dict]:
    """Filter assets by architecture."""
    if arch == "amd64":
        return [
            a
            for a in assets
            if "amd64" in a["name"].lower() or "x86_64" in a["name"].lower()
        ]
    if arch == "arm64":
        return [
            a
            for a in assets
            if "arm64" in a["name"].lower() or "aarch64" in a["name"].lower()
        ]
    return []


def find_sample_asset(assets: list[dict]) -> dict | None:
    """Find a suitable sample asset for analysis."""
    # Try to find Linux x86_64 asset first
    linux_assets = get_platform_assets(assets, "linux")
    for asset in linux_assets:
        if "x86_64" in asset["name"] and asset["name"].endswith(
            (".tar.gz", ".tgz", ".zip"),
        ):
            return asset

    # If no Linux asset, try macOS
    macos_assets = get_platform_assets(assets, "macos")
    for asset in macos_assets:
        if "x86_64" in asset["name"] and asset["name"].endswith(
            (".tar.gz", ".tgz", ".zip"),
        ):
            return asset

    return None


def download_and_find_binary(asset: dict, tool_name: str) -> str | None:
    """Download sample asset and find binary path."""
    console.print(
        f"\n📥 [blue]Downloading sample archive: {asset['name']} to inspect contents...[/blue]",
    )

    temp_path = None
    temp_dir = None
    binary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=os.path.splitext(asset["name"])[1],
        ) as temp_file:
            temp_path = temp_file.name

        download_file(asset["browser_download_url"], temp_path)
        temp_dir = tempfile.mkdtemp()

        # Extract the archive
        extract_archive(temp_path, temp_dir)

        # Find executables
        executables = find_executables(temp_dir)

        console.print("\n🔍 [blue]Executable files found in the archive:[/blue]")
        for exe in executables:
            console.print(f"  - {exe}")

        # Determine binary path
        binary_path = determine_binary_path(executables, tool_name)

        if binary_path:
            console.print(f"\n✅ [green]Detected binary path: {binary_path}[/green]")

        return binary_path

    finally:
        # Clean up
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def extract_archive(archive_path: str, dest_dir: str) -> None:
    """Extract an archive to a destination directory."""
    is_tarball = False
    with open(archive_path, "rb") as f:
        if f.read(2) == b"\x1f\x8b":
            is_tarball = True

    if is_tarball or archive_path.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive_path, mode="r:gz") as tar:
            tar.extractall(path=dest_dir)
    elif archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zip_file:
            zip_file.extractall(path=dest_dir)
    else:
        msg = f"Unsupported archive format: {archive_path}"
        raise ValueError(msg)


def find_executables(directory: str | Path) -> list[str]:
    """Find executable files in a directory structure."""
    executables = []
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            if os.access(file_path, os.X_OK):
                rel_path = os.path.relpath(file_path, directory)
                executables.append(rel_path)
    return executables


def determine_binary_path(executables: list[str], tool_name: str) -> str | None:
    """Determine the most likely binary path based on executables."""
    if not executables:
        return None

    # First try to find an exact name match
    for exe in executables:
        base_name = os.path.basename(exe)
        if base_name.lower() == tool_name.lower():
            return exe

    # Then try to find executables in bin/
    for exe in executables:
        if "bin/" in exe:
            return exe

    # Finally, just take the first executable
    return executables[0]


def generate_tool_config(
    repo: str,
    tool_name: str,
    release: dict,
    binary_path: str | None,
) -> dict:
    """Generate tool configuration based on release information."""
    assets = release["assets"]
    linux_assets = get_platform_assets(assets, "linux")
    macos_assets = get_platform_assets(assets, "macos")

    # Determine if we need architecture conversion
    arch_conversion = any("x86_64" in a["name"] for a in assets) or any(
        "aarch64" in a["name"] for a in assets
    )

    # Create tool configuration
    tool_config = {
        "repo": repo,
        "extract_binary": True,
        "binary_name": tool_name,
    }

    # Add binary path if found
    if binary_path:
        version = release["tag_name"].lstrip("v")
        # Check if there's a version folder in the path
        if version in binary_path:
            binary_path = binary_path.replace(version, "{version}")
        tool_config["binary_path"] = binary_path

    # Add arch_map if needed
    if arch_conversion:
        tool_config["arch_map"] = {"amd64": "x86_64", "arm64": "aarch64"}

    # Generate asset patterns
    platform_specific = bool(linux_assets and macos_assets)
    if platform_specific:
        asset_patterns = generate_platform_specific_patterns(release)
        tool_config["asset_patterns"] = asset_patterns
    else:
        # Single pattern for all platforms
        pattern = generate_single_pattern(release)
        if pattern != "?":
            tool_config["asset_pattern"] = pattern

    return tool_config


def generate_platform_specific_patterns(release: dict) -> dict:
    """Generate platform-specific asset patterns."""
    assets = release["assets"]
    linux_assets = get_platform_assets(assets, "linux")
    macos_assets = get_platform_assets(assets, "macos")
    amd64_assets = get_arch_assets(assets, "amd64")

    patterns = {"linux": "?", "macos": "?"}

    # Find pattern for Linux
    if linux_assets and amd64_assets:
        for asset in linux_assets:
            if "x86_64" in asset["name"] or "amd64" in asset["name"]:
                pattern = asset["name"]
                if "x86_64" in pattern:
                    pattern = pattern.replace("x86_64", "{arch}")
                elif "amd64" in pattern:
                    pattern = pattern.replace("amd64", "{arch}")
                version = release["tag_name"].lstrip("v")
                if version in pattern:
                    pattern = pattern.replace(version, "{version}")
                patterns["linux"] = pattern
                break

    # Find pattern for macOS
    if macos_assets and amd64_assets:
        for asset in macos_assets:
            if "x86_64" in asset["name"] or "amd64" in asset["name"]:
                pattern = asset["name"]
                if "x86_64" in pattern:
                    pattern = pattern.replace("x86_64", "{arch}")
                elif "amd64" in pattern:
                    pattern = pattern.replace("amd64", "{arch}")
                version = release["tag_name"].lstrip("v")
                if version in pattern:
                    pattern = pattern.replace(version, "{version}")
                patterns["macos"] = pattern
                break

    return patterns


def generate_single_pattern(release: dict) -> str:
    """Generate a single asset pattern for all platforms."""
    if not release["assets"]:
        return "?"

    asset_name = release["assets"][0]["name"]
    pattern = asset_name

    # Replace version if present
    version = release["tag_name"].lstrip("v")
    if version in pattern:
        pattern = pattern.replace(version, "{version}")

    if "darwin" in pattern.lower():
        pattern = re.sub(r"(?i)darwin", "{platform}", pattern)

    # Replace architecture if present
    if "x86_64" in pattern:
        pattern = pattern.replace("x86_64", "{arch}")
    elif "amd64" in pattern:
        pattern = pattern.replace("amd64", "{arch}")

    return pattern


def main() -> None:
    """Main function to parse arguments and execute commands."""
    global TOOLS_DIR
    parser = argparse.ArgumentParser(
        description="dotbins - Manage CLI tool binaries in your dotfiles repository",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--tools-dir",
        type=str,
        help=f"Tools directory (default: {TOOLS_DIR})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # list command
    list_parser = subparsers.add_parser("list", help="List available tools")
    list_parser.set_defaults(func=list_tools)

    # update command
    update_parser = subparsers.add_parser("update", help="Update tools")
    update_parser.add_argument(
        "tools",
        nargs="*",
        help="Tools to update (all if not specified)",
    )
    update_parser.add_argument(
        "-p",
        "--platform",
        choices=PLATFORMS,
        help="Only update for specific platform",
    )
    update_parser.add_argument(
        "-a",
        "--architecture",
        choices=ARCHITECTURES,
        help="Only update for specific architecture",
    )
    update_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force update even if binary exists",
    )
    update_parser.add_argument(
        "-s",
        "--shell-setup",
        action="store_true",
        help="Print shell setup instructions",
    )
    update_parser.set_defaults(func=update_tools)

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize directory structure")
    init_parser.set_defaults(func=initialize)

    # analyze command for discovering new tools
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze GitHub releases for a tool",
    )
    analyze_parser.add_argument(
        "repo",
        help="GitHub repository in the format 'owner/repo'",
    )
    analyze_parser.add_argument("--name", help="Name to use for the tool")
    analyze_parser.set_defaults(func=analyze_tool)

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Override tools directory if specified
    if args.tools_dir:
        TOOLS_DIR = Path(args.tools_dir)

    # Execute command or show help
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
