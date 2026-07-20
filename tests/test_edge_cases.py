"""Edge case tests"""
import pytest
from managers.asset_registry import AssetRegistry
from models.asset import AssetRecord


def test_empty_comfyui_history():
    """Test handling of missing/empty history"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    
    # Register with None history
    asset_record = registry.register_asset(
        filename="test.png",
        subfolder="",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        comfy_history=None,
        submitted_workflow=None
    )
    
    assert asset_record.comfy_history is None
    assert asset_record.submitted_workflow is None


def test_very_long_filename():
    """Test handling of very long filenames"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    long_filename = "a" * 500 + ".png"
    
    asset_record = registry.register_asset(
        filename=long_filename,
        subfolder="",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        comfy_history={},
        submitted_workflow={}
    )
    
    assert asset_record.filename == long_filename
    # URL should still be valid (encoded)
    url = asset_record.asset_url
    assert url.startswith("http://")


def test_unicode_characters_in_filename():
    """Test handling of unicode characters"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    
    asset_record = registry.register_asset(
        filename="测试_画像_🎨.png",
        subfolder="文件夹/子文件夹",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        comfy_history={},
        submitted_workflow={}
    )
    
    assert asset_record.filename == "测试_画像_🎨.png"
    url = asset_record.asset_url
    # Should be properly encoded
    assert "测试" not in url  # Should be encoded
    assert url.startswith("http://")


def test_multiple_assets_same_workflow():
    """Test multiple assets from same workflow"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    
    workflow_id = "generate_image"
    for i in range(10):
        registry.register_asset(
            filename=f"output_{i}.png",
            subfolder="",
            folder_type="output",
            workflow_id=workflow_id,
            prompt_id=f"prompt_{i}",
            comfy_history={},
            submitted_workflow={}
        )
    
    # All should be retrievable
    assets = registry.list_assets(workflow_id=workflow_id)
    assert len(assets) == 10


def test_asset_cleanup_on_expiration():
    """Test that expired assets are cleaned up"""
    registry = AssetRegistry(ttl_hours=0.0001, comfyui_base_url="http://localhost:8188")
    
    # Register multiple assets
    asset_ids = []
    for i in range(5):
        record = registry.register_asset(
            filename=f"temp_{i}.png",
            subfolder="",
            folder_type="output",
            workflow_id="generate_image",
            prompt_id=f"prompt_{i}",
            comfy_history={},
            submitted_workflow={}
        )
        asset_ids.append(record.asset_id)
    
    # Wait for expiration
    import time
    time.sleep(1)
    
    # Cleanup
    cleaned = registry.cleanup_expired()
    assert cleaned == 5
    
    # All should be gone
    for asset_id in asset_ids:
        assert registry.get_asset(asset_id) is None


def test_base_url_with_different_ports():
    """Test that asset URLs work with different base URLs"""
    base_urls = [
        "http://localhost:8188",
        "http://127.0.0.1:8188",
        "http://localhost:9000",
        "https://example.com:443"
    ]
    
    for base_url in base_urls:
        registry = AssetRegistry(comfyui_base_url=base_url)
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
        assert url.startswith(base_url.rstrip('/'))
        assert "test.png" in url or "test%2Epng" in url  # Encoded


def test_empty_metadata():
    """Test handling of empty metadata"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    asset_record = registry.register_asset(
        filename="test.png",
        subfolder="",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        metadata={},
        comfy_history={},
        submitted_workflow={}
    )
    
    assert asset_record.metadata == {}
    
    # Should still work
    found = registry.get_asset(asset_record.asset_id)
    assert found.metadata == {}


def test_nested_subfolder():
    """Test nested subfolder paths"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    asset_record = registry.register_asset(
        filename="test.png",
        subfolder="2024/01/15",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        comfy_history={},
        submitted_workflow={}
    )
    
    url = asset_record.asset_url
    # Should have subfolder parameter
    assert "subfolder=" in url
    # Should be encoded
    assert "2024/01/15" not in url  # Should be encoded
