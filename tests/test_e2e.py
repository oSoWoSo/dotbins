"""End-to-end tests for dotbins."""

import os
import tarfile
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from dotbins.cli import _update_tools
from dotbins.config import _config_from_dict
from dotbins.utils import log


@pytest.fixture
def temp_tools_dir() -> Generator[Path, None, None]:
    """Creates a temporary directory to serve as our `tools_dir`.

    Cleans up after the test.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_dummy_tarball(dest: Path, binary_name: str = "mybinary") -> None:
    """Creates a .tar.gz at `dest` containing a single executable file named `binary_name`."""
    with tempfile.TemporaryDirectory() as tmp_extract_dir:
        exe_path = Path(tmp_extract_dir) / binary_name
        exe_path.write_text("#!/usr/bin/env echo\n")
        exe_path.chmod(0o755)
        # Make a tar.gz containing that single file
        with tarfile.open(dest, "w:gz") as tar:
            tar.add(exe_path, arcname=binary_name)


@pytest.mark.parametrize(
    "raw_config",
    [
        # 1) Simple config with a single tool, single pattern
        {
            "tools_dir": "/fake/tools_dir",  # Will get overridden by fixture
            "platforms": {"linux": ["amd64"]},
            "tools": {
                "mytool": {
                    "repo": "fakeuser/mytool",
                    "extract_binary": True,
                    "binary_name": "mybinary",
                    "binary_path": "mybinary",
                    "asset_patterns": "mytool-{version}-linux_{arch}.tar.gz",
                },
            },
        },
        # 2) Config with multiple tools & multiple patterns
        {
            "tools_dir": "/fake/tools_dir",  # Overridden by fixture
            "platforms": {"linux": ["amd64", "arm64"]},
            "tools": {
                "mytool": {
                    "repo": "fakeuser/mytool",
                    "extract_binary": True,
                    "binary_name": "mybinary",
                    "binary_path": "mybinary",
                    "asset_patterns": {
                        "linux": {
                            "amd64": "mytool-{version}-linux_{arch}.tar.gz",
                            "arm64": "mytool-{version}-linux_{arch}.tar.gz",
                        },
                    },
                },
                "othertool": {
                    "repo": "fakeuser/othertool",
                    "extract_binary": True,
                    "binary_name": "otherbin",
                    "binary_path": "otherbin",
                    "asset_patterns": "othertool-{version}-{platform}_{arch}.tar.gz",
                },
            },
        },
    ],
)
def test_e2e_update_tools(temp_tools_dir: Path, raw_config: dict) -> None:
    """Shows an end-to-end test.

    This test:
    - Builds a Config from a dict
    - Mocks out `latest_release_info` to produce predictable asset names
    - Mocks out `download_file` so we skip real network usage
    - Calls `_update_tools` directly
    - Verifies that the binaries are extracted into the correct location.
    """
    config = _config_from_dict(raw_config)
    config.tools_dir = temp_tools_dir

    def mock_latest_release_info(repo: str) -> dict:
        tool_name = repo.split("/")[-1]
        return {
            "tag_name": "v1.2.3",
            "assets": [
                {
                    "name": f"{tool_name}-1.2.3-linux_amd64.tar.gz",
                    "browser_download_url": f"https://example.com/{tool_name}-1.2.3-linux_amd64.tar.gz",
                },
                {
                    "name": f"{tool_name}-1.2.3-linux_arm64.tar.gz",
                    "browser_download_url": f"https://example.com/{tool_name}-1.2.3-linux_arm64.tar.gz",
                },
            ],
        }

    def mock_download_file(url: str, destination: str) -> str:
        log(f"MOCKED download_file from {url} -> {destination}", "info")
        if "mytool" in url:
            create_dummy_tarball(Path(destination), binary_name="mybinary")
        else:  # "othertool" in url
            create_dummy_tarball(Path(destination), binary_name="otherbin")
        return destination

    with (
        patch("dotbins.config.latest_release_info", side_effect=mock_latest_release_info),
        patch("dotbins.download.download_file", side_effect=mock_download_file),
    ):
        _update_tools(
            config=config,
            tools=[],  # empty => means "update all tools"
            platform=None,  # None => "all configured platforms"
            architecture=None,  # None => "all configured archs"
            current=False,
            force=False,
            shell_setup=False,
        )

    for tool_conf in config.tools.values():
        for platform, arch_list in config.platforms.items():
            for arch in arch_list:
                for binary_name in tool_conf.binary_name:
                    bin_file = config.bin_dir(platform, arch) / binary_name
                    assert bin_file.exists(), f"Expected {bin_file} to exist after update!"
                    assert os.access(bin_file, os.X_OK), f"Expected {bin_file} to be executable"
