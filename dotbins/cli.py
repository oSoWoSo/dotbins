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
    DownloadTask,
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


def update_tools(args: argparse.Namespace, config: DotbinsConfig) -> None:
    """Update tools based on command line arguments."""
    tools_to_update, platforms_to_update = _determine_update_targets(args, config)
    _validate_tools(tools_to_update, config)
    config.tools_dir.mkdir(parents=True, exist_ok=True)
    download_tasks, total_count = _prepare_download_tasks(
        tools_to_update,
        platforms_to_update,
        args,
        config,
    )
    downloaded_tasks = _download_files_in_parallel(download_tasks)
    success_count = _process_downloaded_files(downloaded_tasks)
    make_binaries_executable(config)
    _print_completion_summary(config, success_count, total_count, args)


def _determine_update_targets(
    args: argparse.Namespace,
    config: DotbinsConfig,
) -> tuple[list[str], list[str]]:
    """Determine which tools and platforms to update."""
    tools_to_update = args.tools if args.tools else list(config.tools.keys())
    platforms_to_update = [args.platform] if args.platform else config.platform_names
    return tools_to_update, platforms_to_update


def _validate_tools(tools_to_update: list[str], config: DotbinsConfig) -> None:
    """Validate that all tools exist in the configuration."""
    for tool in tools_to_update:
        if tool not in config.tools:
            console.print(f"❌ [bold red]Unknown tool: {tool}[/bold red]")
            sys.exit(1)


def _prepare_download_tasks(
    tools_to_update: list[str],
    platforms_to_update: list[str],
    args: argparse.Namespace,
    config: DotbinsConfig,
) -> tuple[list[DownloadTask], int]:
    """Prepare download tasks for all tools and platforms."""
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
            archs_to_update = _determine_architectures(platform, args, config)
            if not archs_to_update:
                continue

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

    return download_tasks, total_count


def _determine_architectures(
    platform: str,
    args: argparse.Namespace,
    config: DotbinsConfig,
) -> list[str]:
    """Determine which architectures to update for a platform."""
    if args.architecture:
        # Filter to only include the specified architecture if it's supported
        if args.architecture in config.platforms[platform]:
            return [args.architecture]
        console.print(
            f"⚠️ [yellow]Architecture {args.architecture} not configured for platform {platform}, skipping[/yellow]",
        )
        return []
    return config.platforms[platform]


def _download_files_in_parallel(
    download_tasks: list[DownloadTask],
) -> list[tuple[DownloadTask, bool]]:
    """Download files in parallel using ThreadPoolExecutor."""
    console.print(
        f"\n🔄 [blue]Downloading {len(download_tasks)} tools in parallel...[/blue]",
    )
    downloaded_tasks = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(8, len(download_tasks) or 1),
    ) as executor:
        future_to_task = {
            executor.submit(download_task, task): task for task in download_tasks
        }
        for future in concurrent.futures.as_completed(future_to_task):
            task, success = future.result()
            downloaded_tasks.append((task, success))

    return downloaded_tasks


def _process_downloaded_files(downloaded_tasks: list[tuple[DownloadTask, bool]]) -> int:
    """Process downloaded files and return success count."""
    console.print(
        f"\n🔄 [blue]Processing {len(downloaded_tasks)} downloaded tools...[/blue]",
    )
    success_count = 0

    for task, download_success in downloaded_tasks:
        if process_downloaded_task(task, download_success):
            success_count += 1

    return success_count


def _print_completion_summary(
    config: DotbinsConfig,
    success_count: int,
    total_count: int,
    args: argparse.Namespace,
) -> None:
    """Print completion summary and additional instructions."""
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
