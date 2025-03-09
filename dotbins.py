#!/usr/bin/env python3
"""
dotbins - Dotfiles Binary Manager

A utility for managing CLI tool binaries in your dotfiles repository.
Downloads and organizes binaries for popular tools across multiple
platforms (macOS, Linux) and architectures (amd64, arm64).

This tool helps maintain a consistent set of CLI utilities across all your
environments, with binaries tracked in your dotfiles git repository.
"""

import os
import sys
import argparse
import requests
import tarfile
import zipfile
import shutil
from pathlib import Path
import json
import tempfile
import re
import logging
from typing import Dict, List, Optional, Any

# Configuration
DOTFILES_DIR = Path.home() / ".dotfiles"
TOOLS_DIR = DOTFILES_DIR / "tools"

# Target platforms and architectures
PLATFORMS = ["linux", "macos"]
ARCHITECTURES = ["amd64", "arm64"]

# Architecture mapping (our naming -> tool release naming)
ARCH_MAP = {
    # Tool: {our-arch: tool-arch}
    "bat": {"amd64": "x86_64", "arm64": "aarch64"},
    "eza": {"amd64": "x86_64", "arm64": "aarch64"},
    "zoxide": {"amd64": "x86_64", "arm64": "aarch64"}
}

# Platform naming for fzf
PLATFORM_MAP = {
    "macos": "darwin"
}

# Tool definitions with release pattern info
TOOLS = {
    "fzf": {
        "repo": "junegunn/fzf",
        "extract_binary": True,
        "binary_name": "fzf",
        "asset_pattern": "fzf-{version}-{platform}_{arch}.tar.gz",
        "platform_map": PLATFORM_MAP,
    },
    "bat": {
        "repo": "sharkdp/bat",
        "extract_binary": True,
        "arch_map": ARCH_MAP["bat"],
        "asset_patterns": {
            "linux": "bat-v{version}-{arch}-unknown-linux-gnu.tar.gz",
            "macos": "bat-v{version}-{arch}-apple-darwin.tar.gz",
        },
        "binary_path": {"linux": "bat-*/bat", "macos": "bat-*/bat"},
    },
    "eza": {
        "repo": "eza-community/eza",
        "extract_binary": True,
        "arch_map": ARCH_MAP["eza"],
        "binary_name": "eza",
        "asset_patterns": {
            "linux": "eza_{arch}-unknown-linux-gnu.tar.gz",
            "macos": None,  # No macOS binaries available as of now
        },
    },
    "zoxide": {
        "repo": "ajeetdsouza/zoxide",
        "extract_binary": True,
        "arch_map": ARCH_MAP["zoxide"],
        "binary_name": "zoxide",
        "asset_patterns": {
            "linux": "zoxide-{version}-{arch}-unknown-linux-musl.tar.gz",
            "macos": "zoxide-{version}-{arch}-apple-darwin.tar.gz",
        },
    },
}

def setup_logging(verbose: bool = False) -> None:
    """Configure logging level based on verbosity"""
    log_level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

def get_latest_release(repo: str) -> dict:
    """Get the latest release information from GitHub"""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    logging.info(f"Fetching latest release from {url}")
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def find_asset(assets: List[dict], pattern: str) -> Optional[dict]:
    """Find an asset that matches the given pattern"""
    regex_pattern = pattern.replace("{version}", ".*").replace("{arch}", ".*").replace("{platform}", ".*")
    logging.info(f"Looking for asset with pattern: {regex_pattern}")
    
    for asset in assets:
        if re.search(regex_pattern, asset["name"]):
            logging.info(f"Found matching asset: {asset['name']}")
            return asset
    
    return None

def download_file(url: str, destination: str) -> str:
    """Download a file from a URL to a destination path"""
    logging.info(f"Downloading from {url}")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    with open(destination, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    return destination

def extract_from_archive(archive_path: str, destination_dir: Path, binary_path: Optional[str] = None) -> None:
    """Extract a binary from an archive"""
    logging.info(f"Extracting from {archive_path}")
    temp_dir = Path(tempfile.mkdtemp())
    
    if archive_path.endswith('.tar.gz') or archive_path.endswith('.tgz'):
        with tarfile.open(archive_path) as tar:
            tar.extractall(path=temp_dir)
    elif archive_path.endswith('.zip'):
        with zipfile.ZipFile(archive_path) as zip_file:
            zip_file.extractall(path=temp_dir)
    else:
        logging.warning(f"Unknown archive type: {archive_path}")
        
    logging.info(f"Extracted to {temp_dir}")
    
    # If binary_path is provided, use it to locate the binary
    if binary_path:
        # Handle glob patterns in binary_path
        if '*' in binary_path:
            import glob
            matches = list(temp_dir.glob(binary_path))
            if matches:
                source = matches[0]
                logging.info(f"Found binary at {source}")
            else:
                raise FileNotFoundError(f"Could not find binary matching {binary_path}")
        else:
            source = temp_dir / binary_path
    else:
        # Default: assume the binary has the same name as the tool and is in the root
        binaries = list(temp_dir.glob('*'))
        source = None
        
        # Check if there's a single file in the root
        executable_files = [f for f in binaries if f.is_file() and os.access(f, os.X_OK)]
        if len(executable_files) == 1:
            source = executable_files[0]
            logging.info(f"Found single executable: {source}")
        elif len(binaries) == 1 and binaries[0].is_file():
            source = binaries[0]
            logging.info(f"Found single file: {source}")
        else:
            # Try to find binary in subdirectories
            logging.info("Searching subdirectories for binary")
            for subdir in [d for d in binaries if d.is_dir()]:
                subdir_files = list(subdir.glob('*'))
                executable_files = [f for f in subdir_files if f.is_file() and os.access(f, os.X_OK)]
                if len(executable_files) == 1:
                    source = executable_files[0]
                    logging.info(f"Found executable in subdirectory: {source}")
                    break
                    
        if not source:
            # List all files in the temp dir for debugging
            all_files = list(temp_dir.glob('**/*'))
            file_list = '\n'.join([str(f) for f in all_files])
            logging.error(f"Could not determine binary to extract. Files in archive:\n{file_list}")
            raise ValueError(f"Could not determine binary path in {archive_path}")
    
    # Create the destination directory if it doesn't exist
    destination_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy the binary to the destination
    if source.is_file():
        binary_name = source.name
        dest_path = destination_dir / binary_name
        shutil.copy2(source, dest_path)
        logging.info(f"Copied {source} to {dest_path}")
        # Make executable
        dest_path.chmod(dest_path.stat().st_mode | 0o755)
    else:
        # If source is a directory, copy everything in it
        for item in source.iterdir():
            if item.is_file():
                dest_path = destination_dir / item.name
                shutil.copy2(item, dest_path)
                logging.info(f"Copied {item} to {dest_path}")
                # Make executable if it looks like a binary
                if not item.name.endswith(('.txt', '.md', '.conf')) and '.' not in item.name:
                    dest_path.chmod(dest_path.stat().st_mode | 0o755)
    
    # Cleanup
    shutil.rmtree(temp_dir)

def download_tool(tool_name: str, tool_config: dict, platform: str, arch: str, force: bool = False) -> bool:
    """Download a tool for a specific platform and architecture"""
    destination_dir = TOOLS_DIR / platform / arch / "bin"
    destination_dir.mkdir(parents=True, exist_ok=True)
    
    release = get_latest_release(tool_config["repo"])
    version = release["tag_name"].lstrip('v')
    
    logging.info(f"Processing {tool_name} {version} for {platform}/{arch}...")
    
    # Map our arch/platform naming to the tool's naming if needed
    tool_arch = arch
    if "arch_map" in tool_config and arch in tool_config["arch_map"]:
        tool_arch = tool_config["arch_map"][arch]
        logging.info(f"Mapped arch {arch} -> {tool_arch}")
    
    tool_platform = platform
    if "platform_map" in tool_config and platform in tool_config["platform_map"]:
        tool_platform = tool_config["platform_map"][platform]
        logging.info(f"Mapped platform {platform} -> {tool_platform}")
    
    # Determine the asset pattern for this platform
    if "asset_patterns" in tool_config:
        asset_pattern = tool_config["asset_patterns"].get(platform)
        if asset_pattern is None:
            logging.warning(f"⚠️ No asset pattern defined for {tool_name} on {platform}")
            return False
    else:
        asset_pattern = tool_config["asset_pattern"]
    
    # Replace variables in the pattern
    search_pattern = asset_pattern.format(
        version=version,
        platform=tool_platform,
        arch=tool_arch
    )
    
    # Find the matching asset
    asset = find_asset(release["assets"], search_pattern)
    if not asset:
        logging.warning(f"⚠️ Could not find asset matching '{search_pattern}' for {tool_name}")
        return False
    
    # Check if we should skip this download
    binary_name = tool_config.get("binary_name", tool_name)
    binary_path = destination_dir / binary_name
    
    if binary_path.exists() and not force:
        logging.info(f"✓ {tool_name} for {platform}/{arch} already exists (use --force to update)")
        return True
    
    # Download the asset
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(asset["name"])[1]) as temp_file:
        temp_path = temp_file.name
    
    try:
        download_file(asset["browser_download_url"], temp_path)
        
        if tool_config.get("extract_binary", False):
            # Get the binary path if specified
            binary_path = None
            if "binary_path" in tool_config:
                binary_path = tool_config["binary_path"].get(platform)
            
            # Extract the binary from the archive
            extract_from_archive(temp_path, destination_dir, binary_path)
        else:
            # Just copy the file directly
            shutil.copy2(temp_path, destination_dir / tool_config.get("binary_name", asset["name"]))
            # Make executable
            dest_file = destination_dir / tool_config.get("binary_name", asset["name"])
            dest_file.chmod(dest_file.stat().st_mode | 0o755)
        
        logging.info(f"✅ Successfully downloaded {tool_name} for {platform}/{arch}")
        return True
    
    except Exception as e:
        logging.error(f"❌ Error processing {tool_name} for {platform}/{arch}: {e}")
        return False
    
    finally:
        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def make_binaries_executable() -> None:
    """Make all binaries executable"""
    for platform in PLATFORMS:
        for arch in ARCHITECTURES:
            bin_dir = TOOLS_DIR / platform / arch / "bin"
            if bin_dir.exists():
                for binary in bin_dir.iterdir():
                    if binary.is_file():
                        binary.chmod(binary.stat().st_mode | 0o755)

def current_platform() -> tuple:
    """Detect the current platform and architecture"""
    platform = "linux"
    if sys.platform == "darwin":
        platform = "macos"
    
    arch = "amd64"
    machine = os.uname().machine.lower()
    if machine in ["arm64", "aarch64"]:
        arch = "arm64"
    
    return platform, arch

def print_shell_setup() -> None:
    """Print shell setup instructions"""
    print("\n# Add this to your shell configuration file (e.g., .bashrc, .zshrc):")
    print("""
# dotbins - Add platform-specific binaries to PATH
_os=$(uname -s | tr '[:upper:]' '[:lower:]')
[[ "$_os" == "darwin" ]] && _os="macos"

_arch=$(uname -m)
[[ "$_arch" == "x86_64" ]] && _arch="amd64"
[[ "$_arch" == "aarch64" || "$_arch" == "arm64" ]] && _arch="arm64"

export PATH="$HOME/.dotfiles/tools/$_os/$_arch/bin:$PATH"
""")

def list_tools(args) -> None:
    """List available tools"""
    print("Available tools:")
    for tool, config in TOOLS.items():
        print(f"  {tool} (from {config['repo']})")

def update_tools(args) -> None:
    """Update tools based on command line arguments"""
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
        tool_config = TOOLS[tool_name]
        for platform in platforms_to_update:
            for arch in archs_to_update:
                total_count += 1
                if download_tool(tool_name, tool_config, platform, arch, args.force):
                    success_count += 1
    
    make_binaries_executable()
    
    print(f"\nCompleted: {success_count}/{total_count} tools updated successfully")
    
    if success_count > 0:
        print("Don't forget to commit the changes to your dotfiles repository")
    
    if args.shell_setup:
        print_shell_setup()

def initialize(args) -> None:
    """Initialize the tools directory structure"""
    for platform in PLATFORMS:
        for arch in ARCHITECTURES:
            (TOOLS_DIR / platform / arch / "bin").mkdir(parents=True, exist_ok=True)
    
    print("Initialized tools directory structure")
    print_shell_setup()

def analyze_tool(args) -> None:
    """Analyze GitHub releases for a tool to help determine patterns"""
    repo = args.repo
    if not repo or '/' not in repo:
        logging.error("Please provide a valid GitHub repository in the format 'owner/repo'")
        sys.exit(1)
    
    try:
        print(f"Analyzing releases for {repo}...")
        release = get_latest_release(repo)
        version = release["tag_name"].lstrip('v')
        
        print(f"\nLatest release: {release['tag_name']} ({release['name']})")
        print("\nAvailable assets:")
        
        for asset in release["assets"]:
            print(f"  - {asset['name']} ({asset['browser_download_url']})")
        
        # Platform categorization
        print("\nLinux assets:")
        linux_assets = [a["name"] for a in release["assets"] if "linux" in a["name"].lower()]
        for asset in linux_assets:
            print(f"  - {asset}")
        
        print("\nmacOS assets:")
        macos_assets = [a["name"] for a in release["assets"] 
                      if "darwin" in a["name"].lower() or "macos" in a["name"].lower()]
        for asset in macos_assets:
            print(f"  - {asset}")
        
        # Architecture categorization
        print("\nAMD64/x86_64 assets:")
        amd64_assets = [a["name"] for a in release["assets"] 
                      if "amd64" in a["name"].lower() or "x86_64" in a["name"].lower()]
        for asset in amd64_assets:
            print(f"  - {asset}")
        
        print("\nARM64/aarch64 assets:")
        arm64_assets = [a["name"] for a in release["assets"] 
                      if "arm64" in a["name"].lower() or "aarch64" in a["name"].lower()]
        for asset in arm64_assets:
            print(f"  - {asset}")
        
        # Suggest configuration
        tool_name = args.name or repo.split('/')[-1]
        
        platform_specific = False
        if linux_assets and macos_assets:
            platform_specific = True
            
        arch_conversion = False
        if any("x86_64" in a for a in release["assets"]) or any("aarch64" in a for a in release["assets"]):
            arch_conversion = True
            
        print("\nSuggested configuration for TOOLS dictionary:")
        
        if platform_specific:
            linux_pattern = "?"
            macos_pattern = "?"
            
            if linux_assets and "x86_64" in " ".join(linux_assets):
                linux_pattern = linux_assets[0].replace("x86_64", "{arch}")
                linux_pattern = re.sub(r'[0-9]+\.[0-9]+\.[0-9]+', "{version}", linux_pattern)
                
            if macos_assets and "x86_64" in " ".join(macos_assets):
                macos_pattern = macos_assets[0].replace("x86_64", "{arch}")
                macos_pattern = re.sub(r'[0-9]+\.[0-9]+\.[0-9]+', "{version}", macos_pattern)
            
            print(f"""
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
            """)
        else:
            # Single pattern
            pattern = "?"
            if release["assets"]:
                pattern = release["assets"][0]["name"]
                pattern = re.sub(r'[0-9]+\.[0-9]+\.[0-9]+', "{version}", pattern)
                if "linux" in pattern:
                    pattern = pattern.replace("linux", "{platform}")
                elif "darwin" in pattern:
                    pattern = pattern.replace("darwin", "{platform}")
                
                if "x86_64" in pattern:
                    pattern = pattern.replace("x86_64", "{arch}")
                elif "amd64" in pattern:
                    pattern = pattern.replace("amd64", "{arch}")
            
            print(f"""
    "{tool_name}": {{
        "repo": "{repo}",
        "extract_binary": True,  # Set to False for direct download
        {"arch_map": {"amd64": "x86_64", "arm64": "aarch64"}, # Map our naming to tool naming" if arch_conversion else ""}
        "binary_name": "{tool_name}",
        "asset_pattern": "{pattern}",
    }},
            """)
        
    except Exception as e:
        logging.error(f"Error analyzing repo: {e}")
        sys.exit(1)

def main() -> None:
    global TOOLS_DIR
    parser = argparse.ArgumentParser(
        description="dotbins - Manage CLI tool binaries in your dotfiles repository",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--tools-dir", type=str, help=f"Tools directory (default: {TOOLS_DIR})")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # list command
    list_parser = subparsers.add_parser("list", help="List available tools")
    list_parser.set_defaults(func=list_tools)
    
    # update command
    update_parser = subparsers.add_parser("update", help="Update tools")
    update_parser.add_argument("tools", nargs="*", help="Tools to update (all if not specified)")
    update_parser.add_argument("-p", "--platform", choices=PLATFORMS, help="Only update for specific platform")
    update_parser.add_argument("-a", "--architecture", choices=ARCHITECTURES, help="Only update for specific architecture")
    update_parser.add_argument("-f", "--force", action="store_true", help="Force update even if binary exists")
    update_parser.add_argument("-s", "--shell-setup", action="store_true", help="Print shell setup instructions")
    update_parser.set_defaults(func=update_tools)
    
    # init command
    init_parser = subparsers.add_parser("init", help="Initialize directory structure")
    init_parser.set_defaults(func=initialize)
    
    # analyze command for discovering new tools
    analyze_parser = subparsers.add_parser("analyze", help="Analyze GitHub releases for a tool")
    analyze_parser.add_argument("repo", help="GitHub repository in the format 'owner/repo'")
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