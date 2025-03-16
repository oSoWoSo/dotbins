"""Configuration for pytest fixtures used in dotbins tests."""

import tarfile
import tempfile
from pathlib import Path

import pytest
from requests_mock import Mocker


@pytest.fixture
def mock_github_api(requests_mock: Mocker, tmp_path: Path) -> Mocker:
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

    # Create a temporary file for our test binary
    test_binary = tmp_path / "test_binary.tar.gz"

    # Create a simple binary file inside a tarball
    with tempfile.TemporaryDirectory() as tmpdir:
        binary_path = Path(tmpdir) / "test-tool"
        with open(binary_path, "w") as f:
            f.write("#!/bin/sh\necho 'Hello from test tool'\n")

        # Make it executable
        binary_path.chmod(0o755)

        # Create a tarball containing the binary
        with tarfile.open(test_binary, "w:gz") as tar:
            tar.add(binary_path, arcname="test-tool")

    # Read the tarball content
    with open(test_binary, "rb") as f:
        tarball_content = f.read()

    # Mock binary download endpoints
    for asset in release_data["assets"]:
        assert isinstance(asset, dict)
        requests_mock.get(asset["browser_download_url"], content=tarball_content)

    return requests_mock
