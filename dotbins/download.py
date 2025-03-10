"""Download and extraction functions for dotbins."""

from __future__ import annotations

import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from rich.console import Console

from .utils import get_latest_release

if TYPE_CHECKING:
    from .config import DotbinsConfig

# Initialize rich console
console = Console()


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


def download_tool(  # noqa: PLR0912, PLR0915
    tool_name: str,
    platform: str,
    arch: str,
    config: DotbinsConfig,
    force: bool = False,  # noqa: FBT001, FBT002
) -> bool:
    """Download a tool for a specific platform and architecture."""
    tool_config = config.tools.get(tool_name)
    if not tool_config:
        console.print(
            f"❌ [bold red]Tool '{tool_name}' not found in configuration[/bold red]",
        )
        return False

    destination_dir = config.tools_dir / platform / arch / "bin"
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
        arch_maps = config.arch_maps.get(tool_name, {})
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


def make_binaries_executable(config: DotbinsConfig) -> None:
    """Make all binaries executable."""
    for platform in config.platforms:
        for arch in config.architectures:
            bin_dir = config.tools_dir / platform / arch / "bin"
            if bin_dir.exists():
                for binary in bin_dir.iterdir():
                    if binary.is_file():
                        binary.chmod(binary.stat().st_mode | 0o755)
