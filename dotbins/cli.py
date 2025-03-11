"""Command-line interface for dotbins."""

from __future__ import annotations

import argparse
import concurrent.futures
import logging
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from . import __version__
from .analyze import analyze_tool
from .config import DotbinsConfig
from .download import (
    download_task,
    make_binaries_executable,
    prepare_download_task,
    process_downloaded_task,
)
from .utils import print_shell_setup, setup_logging

# Initialize rich console
console = Console()
logger = logging.getLogger(__name__)


def list_tools(_args: Any, config: DotbinsConfig) -> None:
    """List available tools."""
    console.print("🔧 [blue]Available tools:[/blue]")
    for tool, tool_config in config.tools.items():
        console.print(f"  [green]{tool}[/green] (from {tool_config['repo']})")


def update_tools(  # noqa: PLR0912
    args: argparse.Namespace,
    config: DotbinsConfig,
) -> None:
    """Update tools based on command line arguments."""
    tools_to_update = args.tools if args.tools else list(config.tools.keys())

    # Handle specific platform filtering
    platforms_to_update = [args.platform] if args.platform else config.platform_names

    # Validate tools
    for tool in tools_to_update:
        if tool not in config.tools:
            console.print(f"❌ [bold red]Unknown tool: {tool}[/bold red]")
            sys.exit(1)

    # Create the tools directory structure
    config.tools_dir.mkdir(parents=True, exist_ok=True)

    # PHASE 1: Prepare download tasks
    download_tasks = []
    total_count = 0

    for tool_name in tools_to_update:
        for platform in platforms_to_update:
            if platform not in config.platforms:
                console.print(
                    f"⚠️ [yellow]Skipping unknown platform: {platform}[/yellow]",
                )
                continue

            # Get architectures to update
            if args.architecture:
                # Filter to only include the specified architecture if it's supported for this platform
                if args.architecture in config.platforms[platform]:
                    archs_to_update = [args.architecture]
                else:
                    console.print(
                        f"⚠️ [yellow]Architecture {args.architecture} not configured for platform {platform}, skipping[/yellow]",
                    )
                    continue
            else:
                archs_to_update = config.platforms[platform]

            for arch in archs_to_update:
                total_count += 1
                task = prepare_download_task(
                    tool_name,
                    platform,
                    arch,
                    config,
                )
                if task:
                    download_tasks.append(task)

    # PHASE 2: Download files in parallel
    console.print(
        f"\n🔄 [blue]Downloading {len(download_tasks)} tools in parallel...[/blue]",
    )
    downloaded_tasks = []

    # Use ThreadPoolExecutor for parallel downloads
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(8, len(download_tasks) or 1),
    ) as executor:
        # Start the download tasks
        future_to_task = {
            executor.submit(download_task, task): task for task in download_tasks
        }

        # Process completed downloads
        for future in concurrent.futures.as_completed(future_to_task):
            task, success = future.result()
            downloaded_tasks.append((task, success))

    # PHASE 3: Process downloaded files sequentially
    console.print(
        f"\n🔄 [blue]Processing {len(downloaded_tasks)} downloaded tools...[/blue]",
    )
    success_count = 0

    for task, download_success in downloaded_tasks:
        if process_downloaded_task(task, download_success):
            success_count += 1

    # Make all binaries executable
    make_binaries_executable(config)

    console.print(
        f"\n🔄 [blue]Completed: {success_count}/{total_count} tools updated successfully[/blue]",
    )

    if success_count > 0:
        console.print(
            "💾 [green]Don't forget to commit the changes to your dotfiles repository[/green]",
        )

    if args.shell_setup:
        print_shell_setup(config)


def initialize(_args: Any, config: DotbinsConfig) -> None:
    """Initialize the tools directory structure."""
    for platform, architectures in config.platforms.items():
        for arch in architectures:
            (config.tools_dir / platform / arch / "bin").mkdir(
                parents=True,
                exist_ok=True,
            )

    console.print("# 🛠️ [green]dotbins initialized tools directory structure[/green]")
    print_shell_setup(config)


def create_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser."""
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
        help="Tools directory",
    )
    parser.add_argument(
        "--config-file",
        type=str,
        help="Path to configuration file",
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
        help="Only update for specific platform",
    )
    update_parser.add_argument(
        "-a",
        "--architecture",
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

    # version command
    version_parser = subparsers.add_parser("version", help="Print version information")
    version_parser.set_defaults(
        func=lambda _, __: console.print(f"[yellow]dotbins[/] [bold]v{__version__}[/]"),
    )

    return parser


def main() -> None:
    """Main function to parse arguments and execute commands."""
    parser = create_parser()
    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    try:
        # Create config
        config = DotbinsConfig.load_from_file(args.config_file)

        # Override tools directory if specified
        if args.tools_dir:
            config.tools_dir = Path(args.tools_dir)

        # Execute command or show help
        if hasattr(args, "func"):
            args.func(args, config)
        else:
            parser.print_help()

    except Exception as e:
        console.print(f"❌ [bold red]Error: {e!s}[/bold red]")
        console.print_exception()
        sys.exit(1)


if __name__ == "__main__":
    main()
