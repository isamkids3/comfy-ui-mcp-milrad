"""Basic smoke tests for v1 release"""
import pytest
from managers.asset_registry import AssetRegistry
from models.asset import AssetRecord


def test_asset_url_encoding():
    """Verify URL encoding works for special characters"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    asset_record = registry.register_asset(
        filename="test image #2.png",
        subfolder="my folder",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        mime_type="image/png",
        comfy_history={},
        submitted_workflow={}
    )
    
    url = asset_record.asset_url
    
    # Should be properly encoded
    assert "%20" in url  # Space
    assert "%23" in url  # #
    assert "localhost:8188" in url
    assert "test%20image%20%232.png" in url
    assert "my%20folder" in url


def test_asset_identity_lookup():
    """Verify O(1) lookup by identity"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    asset_record = registry.register_asset(
        filename="test.png",
        subfolder="",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        comfy_history={"test": "data"},
        submitted_workflow={"nodes": []}
    )
    
    # Lookup by identity
    found_asset = registry.get_asset_by_identity("test.png", "", "output")
    assert found_asset is not None
    assert found_asset.asset_id == asset_record.asset_id
    assert found_asset.comfy_history["test"] == "data"


def test_list_assets():
    """Verify asset listing and filtering"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    
    # Create test assets
    for i in range(5):
        registry.register_asset(
            filename=f"test_{i}.png",
            subfolder="",
            folder_type="output",
            workflow_id="generate_image" if i < 3 else "generate_song",
            prompt_id=f"prompt_{i}",
            mime_type="image/png" if i < 3 else "audio/mpeg",
            comfy_history={},
            submitted_workflow={}
        )
    
    # Test limit
    assets = registry.list_assets(limit=2)
    assert len(assets) == 2
    
    # Test filtering by workflow_id
    image_assets = registry.list_assets(workflow_id="generate_image")
    assert len(image_assets) == 3
    assert all(a.workflow_id == "generate_image" for a in image_assets)


def test_asset_url_base_url_normalization():
    """Test that trailing slashes in base_url are handled"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188/")  # With trailing slash
    asset_record = registry.register_asset(
        filename="test.png",
        subfolder="",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        comfy_history={},
        submitted_workflow={}
    )
    
    url = asset_record.asset_url
    # Should not have double slashes
    assert "//view" not in url
    assert url.startswith("http://localhost:8188/view")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
