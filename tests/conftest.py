"""Pytest configuration and fixtures"""

import pytest
from managers.asset_registry import AssetRegistry


@pytest.fixture
def asset_registry():
    """Create a fresh AssetRegistry for each test."""
    return AssetRegistry(comfyui_base_url="http://localhost:8188", ttl_hours=24)


@pytest.fixture
def sample_asset_data():
    """Sample asset data for testing."""
    return {
        "filename": "test.png",
        "subfolder": "",
        "folder_type": "output",
        "workflow_id": "generate_image",
        "prompt_id": "test_prompt_123",
        "mime_type": "image/png",
        "width": 512,
        "height": 512,
        "bytes_size": 12345,
        "comfy_history": {"test": "data"},
        "submitted_workflow": {"nodes": []},
        "metadata": {"test": "metadata"}
    }
