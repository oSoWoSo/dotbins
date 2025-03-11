"""Download and extraction functions for dotbins."""

from __future__ import annotations

import logging
import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import requests
from rich.console import Console

from .utils import get_latest_release

if TYPE_CHECKING:
    from .config import DotbinsConfig
# Initialize rich console
console = Console()
logger = logging.getLogger(__name__)


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
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        with open(destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return destination
    except requests.RequestException as e:
        console.print(f"❌ [bold red]Download failed: {e}[/bold red]")
        console.print_exception()  # Replaces logger.exception
        msg = f"Failed to download {url}: {e}"
        raise RuntimeError(msg) from e


def extract_archive(archive_path: str, dest_dir: str) -> None:
    """Extract an archive to a destination directory."""
    try:
        # Check file type
        is_gzip = False
        with open(archive_path, "rb") as f:
            header = f.read(3)
            if header.startswith(b"\x1f\x8b"):
                is_gzip = True

        if is_gzip or archive_path.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive_path, mode="r:gz") as tar:
                tar.extractall(path=dest_dir)
        elif archive_path.endswith((".tar.bz2", ".tbz2")):
            with tarfile.open(archive_path, mode="r:bz2") as tar:
                tar.extractall(path=dest_dir)
        elif archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zip_file:
                zip_file.extractall(path=dest_dir)
        else:
            msg = f"Unsupported archive format: {archive_path}"
            raise ValueError(msg)  # noqa: TRY301
    except Exception as e:
        console.print(f"❌ [bold red]Extraction failed: {e}[/bold red]")
        console.print_exception()  # Replaces logger.error with exc_info=True
        raise


def extract_from_archive(
    archive_path: str,
    destination_dir: Path,
    tool_config: dict,
    platform: str,
) -> None:
    """Extract binaries from an archive."""
    console.print(f"📦 [blue]Extracting from {archive_path} for {platform}[/blue]")
    temp_dir = Path(tempfile.mkdtemp())

    try:
        extract_archive(str(archive_path), str(temp_dir))
        console.print(f"📦 [green]Archive extracted to {temp_dir}[/green]")
        # Debug: List the extracted files
        _log_extracted_files(temp_dir)
        binary_names, binary_paths = _get_binary_config(tool_config)
        if not binary_paths:  # Auto-detect binary paths if not specified
            binary_paths = _detect_binary_paths(temp_dir, binary_names)
        destination_dir.mkdir(parents=True, exist_ok=True)
        _process_binaries(
            temp_dir,
            destination_dir,
            binary_names,
            binary_paths,
            tool_config,
        )

    except Exception as e:
        console.print(f"❌ [bold red]Error extracting archive: {e}[/bold red]")
        console.print_exception()
        raise
    finally:
        shutil.rmtree(temp_dir)


def _get_binary_config(tool_config: dict) -> tuple[list[str], list[str]]:
    """Get binary names and paths from the tool configuration."""
    binary_names = tool_config.get("binary_name", [])
    binary_paths = tool_config.get("binary_path", [])

    if isinstance(binary_names, str):
        binary_names = [binary_names]
    if isinstance(binary_paths, str):
        binary_paths = [binary_paths]

    return binary_names, binary_paths


def _detect_binary_paths(temp_dir: Path, binary_names: list[str]) -> list[str]:
    """Auto-detect binary paths if not specified in configuration."""
    console.print(
        "🔍 [blue]Binary path not specified, attempting auto-detection...[/blue]",
    )
    binary_paths = auto_detect_binary_paths(temp_dir, binary_names)
    if not binary_paths:
        msg = f"Could not auto-detect binary paths for {', '.join(binary_names)}. Please specify binary_path in config."
        raise ValueError(msg)
    console.print(
        f"✅ [green]Auto-detected binary paths: {binary_paths}[/green]",
    )
    return binary_paths


def _process_binaries(
    temp_dir: Path,
    destination_dir: Path,
    binary_names: list[str],
    binary_paths: list[str],
    tool_config: dict,
) -> None:
    """Process each binary by finding it and copying to destination."""
    for i, binary_path_pattern in enumerate(binary_paths):
        # Get corresponding binary name (use last name for extra paths)
        binary_name = binary_names[min(i, len(binary_names) - 1)]

        # Find and copy each binary
        source_path = find_binary_in_extracted_files(
            temp_dir,
            tool_config,
            binary_path_pattern,
        )
        copy_binary_to_destination(source_path, destination_dir, binary_name)


def auto_detect_binary_paths(temp_dir: Path, binary_names: list[str]) -> list[str]:
    """Automatically detect binary paths in an extracted archive.

    Args:
        temp_dir: Directory containing extracted archive
        binary_names: Names of binaries to look for

    Returns:
        List of detected binary paths or empty list if detection fails

    """
    detected_paths = []

    for binary_name in binary_names:
        # Look for exact match first
        exact_matches = list(temp_dir.glob(f"**/{binary_name}"))
        if len(exact_matches) == 1:
            detected_paths.append(str(exact_matches[0].relative_to(temp_dir)))
            continue

        # Look for files containing the name
        partial_matches = list(temp_dir.glob(f"**/*{binary_name}*"))
        executable_matches = [p for p in partial_matches if os.access(p, os.X_OK)]

        if len(executable_matches) == 1:
            detected_paths.append(str(executable_matches[0].relative_to(temp_dir)))
        elif len(executable_matches) > 1:
            # If we have multiple matches, try to find the most likely one
            # (e.g., in a bin/ directory or with exact name match)
            bin_matches = [p for p in executable_matches if "bin/" in str(p)]
            if len(bin_matches) == 1:
                detected_paths.append(str(bin_matches[0].relative_to(temp_dir)))
            else:
                # Give up - we need the user to specify
                return []
        else:
            # No matches found
            return []

    return detected_paths


def _log_extracted_files(temp_dir: Path) -> None:
    """Log the extracted files for debugging."""
    try:
        console.print("📋 [blue]Extracted files:[/blue]")
        for item in temp_dir.glob("**/*"):
            console.print(f"  - {item.relative_to(temp_dir)}")
    except Exception as e:
        console.print(f"❌ Could not list extracted files: {e}")


def find_binary_in_extracted_files(
    temp_dir: Path,
    tool_config: dict,
    binary_path: str,
) -> Path:
    """Find a specific binary in the extracted files."""
    # Replace variables in the binary path
    binary_path = replace_variables_in_path(binary_path, tool_config)

    # Handle glob patterns in binary path
    if "*" in binary_path:
        matches = list(temp_dir.glob(binary_path))
        if not matches:
            msg = f"No files matching {binary_path} in archive"
            raise FileNotFoundError(msg)
        return matches[0]

    # Direct path
    source_path = temp_dir / binary_path
    if not source_path.exists():
        msg = f"Binary not found at {source_path}"
        raise FileNotFoundError(msg)

    return source_path


def copy_binary_to_destination(
    source_path: Path,
    destination_dir: Path,
    binary_name: str,
) -> None:
    """Copy the binary to its destination and set permissions."""
    dest_path = destination_dir / binary_name

    # Copy the binary and set permissions
    shutil.copy2(source_path, dest_path)
    dest_path.chmod(dest_path.stat().st_mode | 0o755)
    console.print(f"✅ [green]Copied binary to {dest_path}[/green]")


def replace_variables_in_path(path: str, tool_config: dict) -> str:
    """Replace variables in a path with their values."""
    if "{version}" in path and "version" in tool_config:
        path = path.replace("{version}", tool_config["version"])

    if "{arch}" in path and "arch" in tool_config:
        path = path.replace("{arch}", tool_config["arch"])

    return path


def validate_tool_config(tool_name: str, config: DotbinsConfig) -> dict | None:
    """Validate that the tool exists in configuration."""
    tool_config = config.tools.get(tool_name)
    if not tool_config:
        console.print(
            f"❌ [bold red]Tool '{tool_name}' not found in configuration[/bold red]",
        )
        return None
    return tool_config


def should_skip_download(
    tool_name: str,
    platform: str,
    arch: str,
    config: DotbinsConfig,
    force: bool,  # noqa: FBT001
) -> bool:
    """Check if download should be skipped (binary already exists)."""
    destination_dir = config.tools_dir / platform / arch / "bin"
    binary_names = config.tools[tool_name].get("binary_name", tool_name)

    # Convert to list if it's a string
    if isinstance(binary_names, str):
        binary_names = [binary_names]

    # Check if all binaries exist
    all_exist = True
    for binary_name in binary_names:
        binary_path = destination_dir / binary_name
        if not binary_path.exists():
            all_exist = False
            break

    if all_exist and not force:
        console.print(
            f"✅ [green]{tool_name} for {platform}/{arch} already exists (use --force to update)[/green]",
        )
        return True
    return False


def get_release_info(tool_config: dict) -> tuple[dict, str]:
    """Get release information for a tool."""
    repo = tool_config["repo"]
    release = get_latest_release(repo)
    version = release["tag_name"].lstrip("v")
    tool_config["version"] = version  # Store for later use
    return release, version


def map_platform_and_arch(
    platform: str,
    arch: str,
    tool_config: dict,
) -> tuple[str, str]:
    """Map platform and architecture names."""
    # Map architecture if needed
    tool_arch = arch
    arch_map = tool_config.get("arch_map", {})
    if arch in arch_map:
        tool_arch = arch_map[arch]
    tool_config["arch"] = tool_arch  # Store for later use

    # Map platform if needed
    tool_platform = platform
    platform_map = tool_config.get("platform_map", {})
    if isinstance(platform_map, dict) and platform in platform_map:
        tool_platform = platform_map[platform]

    return tool_platform, tool_arch


def find_matching_asset(
    tool_config: dict,
    release: dict,
    version: str,
    platform: str,
    arch: str,
    tool_platform: str,
    tool_arch: str,
) -> dict | None:
    """Find a matching asset for the tool."""
    # Determine asset pattern
    asset_pattern = get_asset_pattern(tool_config, platform, arch)
    if not asset_pattern:
        console.print(
            f"⚠️ [yellow]No asset pattern found for {platform}/{arch}[/yellow]",
        )
        return None

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
            f"⚠️ [yellow]No asset matching '{search_pattern}' found[/yellow]",
        )
        return None

    return asset


def get_asset_pattern(  # noqa: PLR0911
    tool_config: dict,
    platform: str,
    arch: str,
) -> str | None:
    """Get the asset pattern for a tool, platform, and architecture."""
    # No asset patterns defined
    if "asset_patterns" not in tool_config:
        console.print("⚠️ [yellow]No asset patterns defined[/yellow]")
        return None

    patterns = tool_config["asset_patterns"]

    # Case 1: String pattern (global pattern for all platforms/architectures)
    if isinstance(patterns, str):
        return patterns

    # Case 2: Dict of patterns by platform
    if isinstance(patterns, dict):
        # If platform not in dict or explicitly set to null, no pattern for this platform
        if platform not in patterns or patterns[platform] is None:
            console.print(
                f"⚠️ [yellow]No asset pattern defined for platform {platform}[/yellow]",
            )
            return None

        platform_patterns = patterns[platform]

        # Case 2a: String pattern for this platform
        if isinstance(platform_patterns, str):
            return platform_patterns

        # Case 3: Dict of patterns by platform and architecture
        if isinstance(platform_patterns, dict):
            # If arch not in dict or explicitly set to null, no pattern for this arch
            if arch not in platform_patterns or platform_patterns[arch] is None:
                console.print(
                    f"⚠️ [yellow]No asset pattern defined for {platform}/{arch}[/yellow]",
                )
                return None

            return platform_patterns[arch]

    # No valid pattern found
    console.print(f"⚠️ [yellow]No asset pattern found for {platform}/{arch}[/yellow]")
    return None


def make_binaries_executable(config: DotbinsConfig) -> None:
    """Make all binaries executable."""
    for platform, architectures in config.platforms.items():
        for arch in architectures:
            bin_dir = config.tools_dir / platform / arch / "bin"
            if bin_dir.exists():
                for binary in bin_dir.iterdir():
                    if binary.is_file():
                        binary.chmod(binary.stat().st_mode | 0o755)


class DownloadTask(NamedTuple):
    """Represents a single download task."""

    tool_name: str
    platform: str
    arch: str
    asset_url: str
    asset_name: str
    tool_config: dict
    destination_dir: Path
    temp_path: Path


def download_task(task: DownloadTask) -> tuple[DownloadTask, bool]:
    """Download a file for a DownloadTask."""
    try:
        console.print(
            f"📥 [blue]Downloading {task.asset_name} for {task.tool_name} ({task.platform}/{task.arch})...[/blue]",
        )
        download_file(task.asset_url, str(task.temp_path))
        return task, True
    except Exception as e:
        console.print(
            f"❌ [bold red]Error downloading {task.asset_name}: {e!s}[/bold red]",
        )
        console.print_exception()
        return task, False


def prepare_download_task(
    tool_name: str,
    platform: str,
    arch: str,
    config: DotbinsConfig,
) -> DownloadTask | None:
    """Prepare a download task without actually downloading.

    Returns a DownloadTask if a download is needed, None if it should be skipped.
    """
    tool_config = validate_tool_config(tool_name, config)
    if not tool_config:
        return None

    destination_dir = config.tools_dir / platform / arch / "bin"
    binary_names = tool_config.get("binary_name", tool_name)
    if isinstance(binary_names, str):
        binary_names = [binary_names]

    all_exist = True
    for binary_name in binary_names:
        binary_path = destination_dir / binary_name
        if not binary_path.exists():
            all_exist = False
            break

    if all_exist:
        console.print(
            f"✅ [green]{tool_name} for {platform}/{arch} already exists (use --force to update)[/green]",
        )
        return None

    try:
        release, version = get_release_info(tool_config)
        tool_platform, tool_arch = map_platform_and_arch(
            platform,
            arch,
            tool_config,
        )
        asset = find_matching_asset(
            tool_config,
            release,
            version,
            platform,
            arch,
            tool_platform,
            tool_arch,
        )
        if not asset:
            return None

        tmp_dir = Path(tempfile.gettempdir())
        temp_path = tmp_dir / asset["browser_download_url"].split("/")[-1]

        return DownloadTask(
            tool_name=tool_name,
            platform=platform,
            arch=arch,
            asset_url=asset["browser_download_url"],
            asset_name=asset["name"],
            tool_config=tool_config,
            destination_dir=destination_dir,
            temp_path=temp_path,
        )

    except Exception as e:
        console.print(
            f"❌ [bold red]Error processing {tool_name} for {platform}/{arch}: {e!s}[/bold red]",
        )
        console.print_exception()
        return None


def process_downloaded_task(task: DownloadTask, success: bool) -> bool:  # noqa: FBT001
    """Process a downloaded file."""
    if not success:
        return False

    try:
        task.destination_dir.mkdir(parents=True, exist_ok=True)
        if task.tool_config.get("extract_binary", False):
            extract_from_archive(
                str(task.temp_path),
                task.destination_dir,
                task.tool_config,
                task.platform,
            )
        else:
            binary_names = task.tool_config.get("binary_name", task.tool_name)
            if isinstance(binary_names, str):
                binary_names = [binary_names]
            binary_name = binary_names[0]

            shutil.copy2(task.temp_path, task.destination_dir / binary_name)
            dest_file = task.destination_dir / binary_name
            dest_file.chmod(dest_file.stat().st_mode | 0o755)

        console.print(
            f"✅ [green]Successfully processed {task.tool_name} for {task.platform}/{task.arch}[/green]",
        )
        return True
    except Exception as e:
        console.print(
            f"❌ [bold red]Error processing {task.tool_name}: {e!s}[/bold red]",
        )
        console.print_exception()
        return False
    finally:
        if task.temp_path.exists():
            task.temp_path.unlink()
