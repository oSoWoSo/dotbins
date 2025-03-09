#!/usr/bin/env python3
"""dotbins - Dotfiles Binary Manager.

A utility for managing CLI tool binaries in your dotfiles repository.
Downloads and organizes binaries for popular tools across multiple
platforms (macOS, Linux) and architectures (amd64, arm64).

This tool helps maintain a consistent set of CLI utilities across all your
environments, with binaries tracked in your dotfiles git repository.
"""

import argparse
import logging
import os
import os.path
import re
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional

import requests
import yaml


# Function to load the configuration
def load_config():
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

        return config
    except Exception as e:
        logging.exception(f"Error loading configuration: {e}")
        # Fallback to defaults
        return {
            "dotfiles_dir": os.path.expanduser("~/.dotfiles"),
            "tools_dir": os.path.expanduser("~/.dotfiles/tools"),
            "platforms": ["linux", "macos"],
            "architectures": ["amd64", "arm64"],
            "tools": {},
        }


# Load configuration
CONFIG = load_config()
DOTFILES_DIR = Path(CONFIG.get("dotfiles_dir"))
TOOLS_DIR = Path(CONFIG.get("tools_dir"))
PLATFORMS = CONFIG.get("platforms", ["linux", "macos"])
ARCHITECTURES = CONFIG.get("architectures", ["amd64", "arm64"])
TOOLS = CONFIG.get("tools", {})


def setup_logging(verbose: bool = False) -> None:
    """Configure logging level based on verbosity."""
    log_level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def get_latest_release(repo: str) -> dict:
    """Get the latest release information from GitHub."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    logging.info(f"Fetching latest release from {url}")
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def find_asset(assets: List[dict], pattern: str) -> Optional[dict]:
    """Find an asset that matches the given pattern."""
    regex_pattern = (
        pattern.replace("{version}", ".*")
        .replace("{arch}", ".*")
        .replace("{platform}", ".*")
    )
    logging.info(f"Looking for asset with pattern: {regex_pattern}")

    for asset in assets:
        if re.search(regex_pattern, asset["name"]):
            logging.info(f"Found matching asset: {asset['name']}")
            return asset

    return None


def download_file(url: str, destination: str) -> str:
    """Download a file from a URL to a destination path."""
    logging.info(f"Downloading from {url}")
    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(destination, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    return destination


def extract_from_archive(
    archive_path: str,
    destination_dir: Path,
    tool_config: dict,
    platform: str,
) -> None:
    """Extract a binary from an archive using explicit paths."""
    logging.info(f"Extracting from {archive_path}")
    temp_dir = Path(tempfile.mkdtemp())

    # Check for gzip file types
    is_tarball = False
    try:
        with open(archive_path, "rb") as f:
            # Check for gzip magic number (1f 8b)
            if f.read(2) == b"\x1f\x8b":
                is_tarball = True
    except Exception as e:
        logging.exception(f"Error checking file type: {e}")

    # Extract based on file type
    try:
        if is_tarball or archive_path.endswith((".tar.gz", ".tgz")):
            logging.info("Processing as tar.gz archive")
            with tarfile.open(archive_path, mode="r:gz") as tar:
                tar.extractall(path=temp_dir)
        elif archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zip_file:
                zip_file.extractall(path=temp_dir)
        else:
            logging.warning(f"Unknown archive type: {archive_path}")
            msg = f"Cannot extract archive: {archive_path}"
            raise ValueError(msg)
    except Exception as e:
        logging.exception(f"Extraction failed: {e}")
        shutil.rmtree(temp_dir)
        raise

    logging.info(f"Archive extracted to {temp_dir}")

    # Debug: List the top-level files
    try:
        logging.info("Extracted files:")
        for item in temp_dir.glob("**/*"):
            logging.info(f"  - {item.relative_to(temp_dir)}")
    except Exception:
        pass

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
                msg = f"Binary not found at {source_path}"
                raise FileNotFoundError(msg)

        # Create the destination directory if needed
        destination_dir.mkdir(parents=True, exist_ok=True)

        # Determine destination filename
        binary_name = tool_config.get("binary_name", source_path.name)
        dest_path = destination_dir / binary_name

        # Copy the binary and set permissions
        shutil.copy2(source_path, dest_path)
        dest_path.chmod(dest_path.stat().st_mode | 0o755)
        logging.info(f"Copied binary to {dest_path}")

    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir)


def download_tool(
    tool_name: str,
    platform: str,
    arch: str,
    force: bool = False,
) -> bool:
    """Download a tool for a specific platform and architecture."""
    tool_config = TOOLS.get(tool_name)
    if not tool_config:
        logging.error(f"Tool '{tool_name}' not found in configuration")
        return False

    destination_dir = TOOLS_DIR / platform / arch / "bin"
    destination_dir.mkdir(parents=True, exist_ok=True)

    # Check if we should skip this download
    binary_name = tool_config.get("binary_name", tool_name)
    binary_path = destination_dir / binary_name

    if binary_path.exists() and not force:
        logging.info(
            f"✓ {tool_name} for {platform}/{arch} already exists (use --force to update)",
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
        arch_maps = CONFIG.get("arch_maps", {}).get(tool_name, {})
        if arch in arch_maps:
            tool_arch = arch_maps[arch]
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
                logging.warning(
                    f"⚠️ No asset pattern defined for {tool_name} on {platform}",
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
            logging.warning(
                f"⚠️ No asset matching '{search_pattern}' found for {tool_name}",
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

            logging.info(
                f"✅ Successfully downloaded {tool_name} for {platform}/{arch}",
            )
            return True

        finally:
            # Cleanup
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    except Exception as e:
        logging.exception(f"❌ Error processing {tool_name} for {platform}/{arch}: {e}")
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


def list_tools(args) -> None:
    """List available tools."""
    print("Available tools:")
    for tool, config in TOOLS.items():
        print(f"  {tool} (from {config['repo']})")


def update_tools(args) -> None:
    """Update tools based on command line arguments."""
    tools_to_update = args.tools if args.tools else TOOLS.keys()
    platforms_to_update = [args.platform] if args.platform else PLATFORMS
    archs_to_update = [args.architecture] if args.architecture else ARCHITECTURES

    # Validate tools
    for tool in tools_to_update:
        if tool not in TOOLS:
            logging.error(f"Unknown tool: {tool}")
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

    print(f"\nCompleted: {success_count}/{total_count} tools updated successfully")

    if success_count > 0:
        print("Don't forget to commit the changes to your dotfiles repository")

    if args.shell_setup:
        print_shell_setup()


def initialize(_args) -> None:  # noqa: ANN001
    """Initialize the tools directory structure."""
    for platform in PLATFORMS:
        for arch in ARCHITECTURES:
            (TOOLS_DIR / platform / arch / "bin").mkdir(parents=True, exist_ok=True)

    print("# Initialized tools directory structure")
    print_shell_setup()


def analyze_tool(args) -> None:
    """Analyze GitHub releases for a tool to help determine patterns."""
    repo = args.repo
    if not repo or "/" not in repo:
        logging.error(
            "Please provide a valid GitHub repository in the format 'owner/repo'",
        )
        sys.exit(1)

    try:
        print(f"Analyzing releases for {repo}...")
        release = get_latest_release(repo)
        release["tag_name"].lstrip("v")

        print(f"\nLatest release: {release['tag_name']} ({release['name']})")
        print("\nAvailable assets:")

        for asset in release["assets"]:
            print(f"  - {asset['name']} ({asset['browser_download_url']})")

        # Platform categorization
        print("\nLinux assets:")
        linux_assets = [
            a["name"] for a in release["assets"] if "linux" in a["name"].lower()
        ]
        for asset in linux_assets:
            print(f"  - {asset}")

        print("\nmacOS assets:")
        macos_assets = [
            a["name"]
            for a in release["assets"]
            if "darwin" in a["name"].lower() or "macos" in a["name"].lower()
        ]
        for asset in macos_assets:
            print(f"  - {asset}")

        # Architecture categorization
        print("\nAMD64/x86_64 assets:")
        amd64_assets = [
            a["name"]
            for a in release["assets"]
            if "amd64" in a["name"].lower() or "x86_64" in a["name"].lower()
        ]
        for asset in amd64_assets:
            print(f"  - {asset}")

        print("\nARM64/aarch64 assets:")
        arm64_assets = [
            a["name"]
            for a in release["assets"]
            if "arm64" in a["name"].lower() or "aarch64" in a["name"].lower()
        ]
        for asset in arm64_assets:
            print(f"  - {asset}")

        # Suggest configuration
        tool_name = args.name or repo.split("/")[-1]

        platform_specific = False
        if linux_assets and macos_assets:
            platform_specific = True

        if any("x86_64" in a for a in release["assets"]) or any(
            "aarch64" in a for a in release["assets"]
        ):
            pass

        print("\nSuggested configuration for TOOLS dictionary:")

        if platform_specific:
            linux_pattern = "?"
            macos_pattern = "?"

            if linux_assets and "x86_64" in " ".join(linux_assets):
                linux_pattern = linux_assets[0].replace("x86_64", "{arch}")
                linux_pattern = re.sub(
                    r"[0-9]+\.[0-9]+\.[0-9]+",
                    "{version}",
                    linux_pattern,
                )

            if macos_assets and "x86_64" in " ".join(macos_assets):
                macos_pattern = macos_assets[0].replace("x86_64", "{arch}")
                macos_pattern = re.sub(
                    r"[0-9]+\.[0-9]+\.[0-9]+",
                    "{version}",
                    macos_pattern,
                )

            print(
                f"""
    "{tool_name}": {{
        "repo": "{repo}",
        "extract_binary": True,  # Set to False for direct download
        {"arch_map": {"amd64": "x86_64", "arm64": "aarch64"}, # Map our naming to tool naming" if arch_conversion else ""}
        "binary_name": "{tool_name}",
        "asset_patterns": {{
            "linux": "{linux_pattern}",
            "macos": "{macos_pattern}",
        }},
    }},
            """,
            )
        else:
            # Single pattern
            pattern = "?"
            if release["assets"]:
                pattern = release["assets"][0]["name"]
                pattern = re.sub(r"[0-9]+\.[0-9]+\.[0-9]+", "{version}", pattern)
                if "linux" in pattern:
                    pattern = pattern.replace("linux", "{platform}")
                elif "darwin" in pattern:
                    pattern = pattern.replace("darwin", "{platform}")

                if "x86_64" in pattern:
                    pattern = pattern.replace("x86_64", "{arch}")
                elif "amd64" in pattern:
                    pattern = pattern.replace("amd64", "{arch}")

            print(
                f"""
    "{tool_name}": {{
        "repo": "{repo}",
        "extract_binary": True,  # Set to False for direct download
        {"arch_map": {"amd64": "x86_64", "arm64": "aarch64"}, # Map our naming to tool naming" if arch_conversion else ""}
        "binary_name": "{tool_name}",
        "asset_pattern": "{pattern}",
    }},
            """,
            )

    except Exception:
        logging.exception("Error analyzing repo")
        sys.exit(1)


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
