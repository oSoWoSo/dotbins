#!/usr/bin/env python3
"""
Debug script for dotbins.py to help diagnose download and extraction issues.
"""

import os
import sys
import requests
import tempfile
import shutil
import magic  # Install with: pip install python-magic
from pathlib import Path

# Import the tools configuration from dotbins
from dotbins import TOOLS, get_latest_release, find_asset


def debug_tool_download(tool_name, platform, architecture):
    """Debug the download process for a specific tool, platform, and architecture"""
    if tool_name not in TOOLS:
        print(f"Error: Tool '{tool_name}' not found in configuration")
        return

    print(f"\n==== Debugging {tool_name} for {platform}/{architecture} ====")

    # Get tool configuration
    tool_config = TOOLS[tool_name]
    repo = tool_config["repo"]
    print(f"Tool Repository: {repo}")

    # Get release info
    try:
        release = get_latest_release(repo)
        version = release["tag_name"].lstrip("v")
        print(f"Latest release: {release['tag_name']} ({version})")
    except Exception as e:
        print(f"Error fetching release info: {e}")
        return

    # Map architecture if needed
    tool_arch = architecture
    if "arch_map" in tool_config and architecture in tool_config["arch_map"]:
        tool_arch = tool_config["arch_map"][architecture]
        print(f"Architecture mapped: {architecture} → {tool_arch}")

    # Map platform if needed
    tool_platform = platform
    if "platform_map" in tool_config and platform in tool_config["platform_map"]:
        tool_platform = tool_config["platform_map"][platform]
        print(f"Platform mapped: {platform} → {tool_platform}")

    # Determine asset pattern
    if "asset_patterns" in tool_config:
        asset_pattern = tool_config["asset_patterns"].get(platform)
        if asset_pattern is None:
            print(f"No asset pattern defined for {tool_name} on {platform}")
            return
    else:
        asset_pattern = tool_config.get("asset_pattern")

    print(f"Asset pattern: {asset_pattern}")

    # Replace variables in pattern
    search_pattern = asset_pattern.format(
        version=version, platform=tool_platform, arch=tool_arch
    )
    print(f"Search pattern: {search_pattern}")

    # Find matching asset
    asset = find_asset(release["assets"], search_pattern)
    if not asset:
        print(f"Could not find asset matching '{search_pattern}'")
        print("Available assets:")
        for a in release["assets"]:
            print(f"  - {a['name']}")
        return

    print(f"Found matching asset: {asset['name']}")
    print(f"Download URL: {asset['browser_download_url']}")

    # Create a debug directory
    debug_dir = Path("dotbins_debug")
    debug_dir.mkdir(exist_ok=True)

    # Download the asset
    download_path = debug_dir / asset["name"]
    try:
        print(f"Downloading to: {download_path}")
        response = requests.get(asset["browser_download_url"], stream=True)
        response.raise_for_status()

        with open(download_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Get file information
        file_size = download_path.stat().st_size
        print(f"File size: {file_size} bytes")

        # Check the file type using python-magic
        try:
            file_type = magic.from_file(str(download_path))
            mime_type = magic.from_file(str(download_path), mime=True)
            print(f"File type (magic): {file_type}")
            print(f"MIME type: {mime_type}")
        except Exception as e:
            print(f"Could not determine file type: {e}")

        # Check file extension
        file_ext = download_path.suffix
        print(f"File extension: {file_ext}")

        # For tar.gz that might be incorrectly named as .gz
        if file_ext == ".gz" and mime_type == "application/gzip":
            print("Note: This might be a tar.gz file with incorrect extension")

        # Print first few bytes as hex for further inspection
        try:
            with open(download_path, "rb") as f:
                header = f.read(16)
                hex_header = " ".join(f"{b:02x}" for b in header)
                print(f"File header (hex): {hex_header}")

                # Check if it starts with the gzip magic number (1f 8b)
                if header.startswith(b"\x1f\x8b"):
                    print("This is a gzip-compressed file (has gzip magic number)")
        except Exception as e:
            print(f"Could not read file header: {e}")

    except Exception as e:
        print(f"Error downloading asset: {e}")


def main():
    """Main function to run the debug script"""
    print("dotbins Debugger")
    print("================")

    # Ensure python-magic is installed
    try:
        import magic
    except ImportError:
        print("Error: The 'python-magic' package is required for this script.")
        print("Install it with: pip install python-magic")

        if sys.platform == "darwin":  # macOS
            print("On macOS, you may also need to install libmagic:")
            print("brew install libmagic")
        elif sys.platform == "win32":  # Windows
            print("On Windows, you may need additional configuration:")
            print("See: https://github.com/ahupp/python-magic#dependencies")

        return

    # Define some common tools and platforms to debug
    tools_to_debug = ["fzf", "bat", "eza", "zoxide"]
    platforms = ["linux", "macos"]
    archs = ["amd64"]

    # Allow selecting a specific tool from command line
    if len(sys.argv) > 1:
        tools_to_debug = [sys.argv[1]]

    # Debug each tool
    for tool in tools_to_debug:
        for platform in platforms:
            for arch in archs:
                debug_tool_download(tool, platform, arch)

    print("\nDebug information saved to the 'dotbins_debug' directory")
    print("Share this output and the downloaded files for troubleshooting")


if __name__ == "__main__":
    main()
