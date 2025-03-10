"""Command-line interface for dotbins."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from rich.console import Console

from .analyze import analyze_tool
from .config import ARCHITECTURES, PLATFORMS, TOOLS, TOOLS_DIR
from .download import download_tool, make_binaries_executable
from .utils import print_shell_setup, setup_logging

# Initialize rich console
console = Console()


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


def initialize(_args: Any = None) -> None:
    """Initialize the tools directory structure."""
    for platform in PLATFORMS:
        for arch in ARCHITECTURES:
            (TOOLS_DIR / platform / arch / "bin").mkdir(parents=True, exist_ok=True)

    console.print("🛠️ [green]Initialized tools directory structure[/green]")
    print_shell_setup()


def main() -> None:
    """Main function to parse arguments and execute commands."""
    global TOOLS_DIR  # This is needed to modify the global TOOLS_DIR from config
    from .config import TOOLS_DIR as original_tools_dir

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
        help=f"Tools directory (default: {original_tools_dir})",
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
        from pathlib import Path

        TOOLS_DIR = Path(args.tools_dir)
        sys.modules[__name__].TOOLS_DIR = TOOLS_DIR
        # Also update it in other modules that use it
        from .config import TOOLS_DIR as config_tools_dir

        sys.modules[config_tools_dir.__module__].TOOLS_DIR = TOOLS_DIR
        from .download import TOOLS_DIR as download_tools_dir

        sys.modules[download_tools_dir.__module__].TOOLS_DIR = TOOLS_DIR

    # Execute command or show help
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
