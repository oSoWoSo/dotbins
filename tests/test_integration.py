"""Integration tests for the dotbins module."""

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch

import dotbins


class TestIntegration:
    """Integration tests for dotbins."""


def test_initialization(
    temp_dir: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Test the 'init' command."""
    # Set up environment
    monkeypatch.setattr(
        dotbins.config,
        "CONFIG",
        {
            "dotfiles_dir": str(temp_dir),
            "tools_dir": str(temp_dir / "tools"),
            "platforms": ["linux", "macos"],
            "architectures": ["amd64", "arm64"],
            "tools": {},
        },
    )
    monkeypatch.setattr(dotbins.config, "TOOLS_DIR", temp_dir / "tools")
    monkeypatch.setattr(dotbins.config, "PLATFORMS", ["linux", "macos"])
    monkeypatch.setattr(dotbins.config, "ARCHITECTURES", ["amd64", "arm64"])

    # Run init command
    with patch.object(sys, "argv", ["dotbins", "init"]):
        dotbins.main()

    # Check if directories were created
    for platform in ["linux", "macos"]:
        for arch in ["amd64", "arm64"]:
            assert (temp_dir / "tools" / platform / arch / "bin").exists()

    # Check if shell setup was printed
    captured = capsys.readouterr()
    assert "Add this to your shell configuration file" in captured.out


def test_list_tools(
    temp_dir: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Test the 'list' command."""
    # Set up environment
    monkeypatch.setattr(
        dotbins.config,
        "CONFIG",
        {
            "dotfiles_dir": str(temp_dir),
            "tools_dir": str(temp_dir / "tools"),
            "platforms": ["linux", "macos"],
            "architectures": ["amd64", "arm64"],
            "tools": {
                "test-tool": {
                    "repo": "test/tool",
                    "extract_binary": True,
                    "binary_name": "test-tool",
                    "binary_path": "test-tool",
                    "asset_pattern": "test-tool-{version}-{platform}_{arch}.tar.gz",
                },
            },
        },
    )
    monkeypatch.setattr(
        dotbins.config,
        "TOOLS",
        {
            "test-tool": {
                "repo": "test/tool",
                "extract_binary": True,
                "binary_name": "test-tool",
                "binary_path": "test-tool",
                "asset_pattern": "test-tool-{version}-{platform}_{arch}.tar.gz",
            },
        },
    )

    # Run list command
    with patch.object(sys, "argv", ["dotbins", "list"]):
        dotbins.main()

    # Check if tool was listed
    captured = capsys.readouterr()
    assert "test-tool" in captured.out
    assert "test/tool" in captured.out


def test_update_tool(
    temp_dir: Path,
    monkeypatch: MonkeyPatch,
    mock_github_api: Any,  # noqa: ARG001
) -> None:
    """Test updating a specific tool."""
    # Set up mock environment
    test_tool_config = {
        "repo": "test/tool",
        "extract_binary": True,
        "binary_name": "test-tool",
        "binary_path": "test-tool",
        "asset_pattern": "test-tool-{version}-{platform}_{arch}.tar.gz",
        "platform_map": "macos:darwin",
    }

    monkeypatch.setattr(
        dotbins.config,
        "CONFIG",
        {
            "dotfiles_dir": str(temp_dir),
            "tools_dir": str(temp_dir / "tools"),
            "platforms": ["linux"],
            "architectures": ["amd64"],
            "tools": {"test-tool": test_tool_config},
        },
    )
    monkeypatch.setattr(dotbins.config, "TOOLS_DIR", temp_dir / "tools")
    monkeypatch.setattr(dotbins.config, "PLATFORMS", ["linux"])
    monkeypatch.setattr(dotbins.config, "ARCHITECTURES", ["amd64"])
    monkeypatch.setattr(dotbins.config, "TOOLS", {"test-tool": test_tool_config})

    # Create a mock tarball with a binary inside
    bin_dir = temp_dir / "tools" / "linux" / "amd64" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    # Create a test binary tarball
    _create_test_tarball(temp_dir / "test_binary.tar.gz", "test-tool")

    # Mock the download_file function to use our test tarball
    def mock_download_file(_url: str, destination: str) -> str:
        shutil.copy(temp_dir / "test_binary.tar.gz", destination)
        return destination

    monkeypatch.setattr(dotbins.download, "download_file", mock_download_file)

    # Run update command
    with patch.object(sys, "argv", ["dotbins", "update", "test-tool"]):
        dotbins.main()

    # Check if binary was installed
    assert (bin_dir / "test-tool").exists()


def _create_test_tarball(path: Path, binary_name: str) -> None:
    """Create a test tarball with a binary inside."""
    import tarfile

    # Create a temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a dummy binary file
        binary_path = Path(tmpdir) / binary_name
        with open(binary_path, "w") as f:
            f.write("#!/bin/sh\necho 'Hello from test tool'\n")

        # Make it executable
        binary_path.chmod(0o755)  # nosec: B103

        # Create tarball
        with tarfile.open(path, "w:gz") as tar:
            tar.add(binary_path, arcname=binary_name)


def test_analyze_tool(
    capsys: CaptureFixture[str],
    mock_github_api: Any,  # noqa: ARG001
) -> None:
    """Test analyzing a GitHub repo for release patterns."""
    # Run analyze command
    # We need to patch sys.exit to prevent it from actually exiting in the test
    with (
        patch.object(sys, "argv", ["dotbins", "analyze", "test/tool"]),
        patch.object(sys, "exit"),
    ):
        dotbins.main()

    # Check output
    captured = capsys.readouterr()
    assert "Analyzing releases for test/tool" in captured.out
    assert "Suggested configuration for YAML tools file" in captured.out

    # Check for proper YAML format
    assert "tool:" in captured.out  # The key should be output
    assert "repo: test/tool" in captured.out
    assert "extract_binary: true" in captured.out

    # Make sure the output is in valid YAML format
    yaml_text = captured.out.split("Suggested configuration for YAML tools file:")[
        1
    ].strip()
    try:
        # This should not raise an exception if the YAML is valid
        yaml.safe_load(yaml_text)
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"Generated YAML is invalid: {e}")


def test_cli_no_command(capsys: CaptureFixture[str]) -> None:
    """Test running CLI with no command."""
    with patch.object(sys, "argv", ["dotbins"]):
        dotbins.main()

    # Should show help
    captured = capsys.readouterr()
    assert "usage: dotbins" in captured.out


def test_cli_unknown_tool(monkeypatch: MonkeyPatch) -> None:
    """Test updating an unknown tool."""
    monkeypatch.setattr(dotbins.config, "TOOLS", {})  # Empty tools dict

    # Should exit with error
    with (
        pytest.raises(SystemExit),
        patch.object(sys, "argv", ["dotbins", "update", "unknown-tool"]),
    ):
        dotbins.main()


def test_cli_tools_dir_override(temp_dir: Path, monkeypatch: MonkeyPatch) -> None:
    """Test overriding tools directory via CLI."""
    custom_dir = temp_dir / "custom_tools"

    # Mock necessary components
    monkeypatch.setattr(
        dotbins.config,
        "CONFIG",
        {
            "dotfiles_dir": str(temp_dir),
            "tools_dir": str(temp_dir / "default_tools"),  # Default dir
            "platforms": ["linux"],
            "architectures": ["amd64"],
            "tools": {},
        },
    )

    # Run init with custom tools dir
    with patch.object(sys, "argv", ["dotbins", "--tools-dir", str(custom_dir), "init"]):
        dotbins.main()

    # Check if directories were created in the custom location
    assert (custom_dir / "linux" / "amd64" / "bin").exists()
