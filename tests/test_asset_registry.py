"""Unit tests for AssetRegistry"""
import pytest
import time
from datetime import datetime, timedelta
from managers.asset_registry import AssetRegistry
from models.asset import AssetRecord


def test_register_and_lookup():
    """Test basic registration and lookup"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    asset_record = registry.register_asset(
        filename="test.png",
        subfolder="",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_prompt_123",
        mime_type="image/png",
        width=512,
        height=512,
        bytes_size=12345,
        comfy_history={"outputs": {}},
        submitted_workflow={"nodes": []}
    )
    
    # Test lookup by identity
    found = registry.get_asset_by_identity("test.png", "", "output")
    assert found is not None
    assert found.asset_id == asset_record.asset_id
    
    # Test lookup by ID
    found = registry.get_asset(asset_record.asset_id)
    assert found is not None
    assert found.filename == "test.png"
    assert found.width == 512
    assert found.height == 512


def test_special_characters_in_filename():
    """Test URL encoding with special characters"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    asset_record = registry.register_asset(
        filename="test image #2.png",
        subfolder="my folder/sub",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        comfy_history={},
        submitted_workflow={}
    )
    
    url = asset_record.asset_url
    # Verify URL encoding
    assert "test%20image%20%232.png" in url
    assert "my%20folder%2Fsub" in url
    # Should not have unencoded spaces
    assert " " not in url.split("?")[1] if "?" in url else True


def test_duplicate_filename_handling():
    """Test what happens with same filename (should return existing and update)"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    
    # Register same filename twice
    record1 = registry.register_asset(
        filename="duplicate.png",
        subfolder="",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="prompt_1",
        comfy_history={"v1": "data"},
        submitted_workflow={}
    )
    
    record2 = registry.register_asset(
        filename="duplicate.png",
        subfolder="",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="prompt_2",
        comfy_history={"v2": "data"},
        submitted_workflow={}
    )
    
    # Should return the same asset (deduplication - updates existing)
    assert record1.asset_id == record2.asset_id
    
    # Latest should win on identity lookup (updates existing)
    asset = registry.get_asset_by_identity("duplicate.png", "", "output")
    assert asset is not None
    # Should have updated history
    assert asset.comfy_history["v2"] == "data"
    # Should still have same asset_id
    assert asset.asset_id == record1.asset_id


def test_list_assets_filtering():
    """Test asset listing with filtering"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    
    # Register multiple assets
    for i in range(5):
        registry.register_asset(
            filename=f"image_{i}.png",
            subfolder="",
            folder_type="output",
            workflow_id="generate_image" if i % 2 == 0 else "generate_song",
            prompt_id=f"prompt_{i}",
            mime_type="image/png" if i % 2 == 0 else "audio/mpeg",
            comfy_history={},
            submitted_workflow={}
        )
    
    # Test limit
    assets = registry.list_assets(limit=2)
    assert len(assets) <= 2
    
    # Test workflow filtering
    image_assets = registry.list_assets(workflow_id="generate_image")
    assert len(image_assets) == 3  # 0, 2, 4
    assert all(a.workflow_id == "generate_image" for a in image_assets)
    
    # Test sorting (newest first)
    all_assets = registry.list_assets(limit=10)
    assert len(all_assets) == 5
    # Check they're sorted by created_at descending
    for i in range(len(all_assets) - 1):
        assert all_assets[i].created_at >= all_assets[i + 1].created_at


def test_asset_expiration():
    """Test TTL cleanup works"""
    # Use very short TTL for testing
    registry = AssetRegistry(ttl_hours=0.0001, comfyui_base_url="http://localhost:8188")  # ~0.36 seconds
    
    asset_record = registry.register_asset(
        filename="temp.png",
        subfolder="",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        comfy_history={},
        submitted_workflow={}
    )
    
    asset_id = asset_record.asset_id
    
    # Asset should exist immediately
    assert registry.get_asset(asset_id) is not None
    
    # Wait for expiration
    time.sleep(1)
    
    # Cleanup should remove it
    registry.cleanup_expired()
    assert registry.get_asset(asset_id) is None
    
    # Identity lookup should also return None
    assert registry.get_asset_by_identity("temp.png", "", "output") is None


def test_empty_subfolder():
    """Test handling of empty subfolder"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    asset_record = registry.register_asset(
        filename="test.png",
        subfolder="",  # Empty
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        comfy_history={},
        submitted_workflow={}
    )
    
    url = asset_record.asset_url
    # Should not have empty subfolder parameter
    assert "subfolder=&" not in url
    assert "subfolder=" not in url or "subfolder=" in url and url.split("subfolder=")[1].startswith("&")


def test_provenance_storage():
    """Test that comfy_history and submitted_workflow are stored"""
    registry = AssetRegistry(comfyui_base_url="http://localhost:8188")
    history = {"outputs": {"1": {"images": []}}}
    workflow = {"nodes": {"1": {"class_type": "KSampler"}}}
    
    asset_record = registry.register_asset(
        filename="test.png",
        subfolder="",
        folder_type="output",
        workflow_id="generate_image",
        prompt_id="test_123",
        comfy_history=history,
        submitted_workflow=workflow
    )
    
    assert asset_record.comfy_history == history
    assert asset_record.submitted_workflow == workflow
    
    # Retrieve and verify
    found = registry.get_asset(asset_record.asset_id)
    assert found.comfy_history == history
    assert found.submitted_workflow == workflow
