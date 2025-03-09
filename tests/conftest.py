import os
import tempfile
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


@pytest.fixture
def mock_config_file(temp_dir):
    """Create a mock tools.yaml configuration file."""
    config = {
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
    }

    config_path = temp_dir / "tools.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


@pytest.fixture
def mock_github_api(requests_mock):
    """Mock GitHub API responses."""
    # Mock the latest release endpoint
    release_data = {
        "tag_name": "v1.0.0",
        "name": "Release 1.0.0",
        "assets": [
            {
                "name": "test-tool-1.0.0-linux_amd64.tar.gz",
                "browser_download_url": "https://example.com/test-tool-1.0.0-linux_amd64.tar.gz",
            },
            {
                "name": "test-tool-1.0.0-linux_arm64.tar.gz",
                "browser_download_url": "https://example.com/test-tool-1.0.0-linux_arm64.tar.gz",
            },
            {
                "name": "test-tool-1.0.0-darwin_amd64.tar.gz",
                "browser_download_url": "https://example.com/test-tool-1.0.0-darwin_amd64.tar.gz",
            },
            {
                "name": "test-tool-1.0.0-darwin_arm64.tar.gz",
                "browser_download_url": "https://example.com/test-tool-1.0.0-darwin_arm64.tar.gz",
            },
        ],
    }

    requests_mock.get(
        "https://api.github.com/repos/test/tool/releases/latest",
        json=release_data,
    )

    # Mock binary download endpoints
    for asset in release_data["assets"]:
        with open(
            os.path.join(os.path.dirname(__file__), "data", "test_binary.tar.gz"),
            "rb",
        ) as f:
            requests_mock.get(asset["browser_download_url"], content=f.read())

    return requests_mock
