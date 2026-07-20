"""Asset registry for tracking generated assets"""

import logging
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from models.asset import AssetRecord

logger = logging.getLogger("MCP_Server")


def _make_asset_key(filename: str, subfolder: str, folder_type: str) -> str:
    """Create a stable lookup key from asset identity."""
    return f"{folder_type}:{subfolder}:{filename}"


class AssetRegistry:
    """Manages tracking of generated assets for inline viewing.
    
    Uses (filename, subfolder, type) as stable identity instead of URL,
    making the system robust to URL changes (e.g., different hostnames).
    """
    
    def __init__(self, ttl_hours: int = 24, comfyui_base_url: str = "http://localhost:8188"):
        self._assets: Dict[str, AssetRecord] = {}  # asset_id -> AssetRecord
        self._asset_key_to_id: Dict[str, str] = {}  # (filename, subfolder, type) -> asset_id
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self.ttl_hours = ttl_hours
        self.comfyui_base_url = comfyui_base_url
        logger.info(f"Initialized AssetRegistry with TTL: {ttl_hours} hours")
    
    def register_asset(
        self,
        filename: str,
        subfolder: str,
        folder_type: str,
        workflow_id: str,
        prompt_id: str,
        mime_type: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        bytes_size: Optional[int] = None,
        comfy_history: Optional[Dict[str, Any]] = None,
        submitted_workflow: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ) -> AssetRecord:
        """Register a new asset and return AssetRecord with asset_id.
        
        Uses (filename, subfolder, type) as stable identity instead of URL.
        """
        with self._lock:
            # Create stable lookup key
            asset_key = _make_asset_key(filename, subfolder, folder_type)
            
            # Check if asset already exists (deduplication)
            existing_id = self._asset_key_to_id.get(asset_key)
            if existing_id and existing_id in self._assets:
                existing = self._assets[existing_id]
                # Check if expired
                if existing.expires_at and datetime.now() > existing.expires_at:
                    # Remove expired asset
                    del self._assets[existing_id]
                    del self._asset_key_to_id[asset_key]
                else:
                    # Update existing asset with new metadata/history if provided
                    if comfy_history is not None:
                        existing.comfy_history = comfy_history
                    if submitted_workflow is not None:
                        existing.submitted_workflow = submitted_workflow
                    logger.debug(f"Asset {asset_key} already registered, returning existing record")
                    return existing
            
            # Generate asset_id (UUID-based for uniqueness)
            asset_id = str(uuid.uuid4())
            
            # Calculate expiration
            expires_at = datetime.now() + timedelta(hours=self.ttl_hours)
            
            # Create record
            record = AssetRecord(
                asset_id=asset_id,
                filename=filename,
                subfolder=subfolder,
                folder_type=folder_type,
                prompt_id=prompt_id,
                workflow_id=workflow_id,
                created_at=datetime.now(),
                expires_at=expires_at,
                mime_type=mime_type or "application/octet-stream",
                width=width,
                height=height,
                bytes_size=bytes_size or 0,
                sha256=None,  # Will be computed if needed
                comfy_history=comfy_history,
                submitted_workflow=submitted_workflow,
                metadata=metadata or {},
                session_id=session_id
            )
            
            # Set base URL for asset URL computation
            record.set_base_url(self.comfyui_base_url)
            
            self._assets[asset_id] = record
            self._asset_key_to_id[asset_key] = asset_id
            
            logger.debug(f"Registered asset {asset_id} ({asset_key}) for workflow {workflow_id}")
            return record
    
    def get_asset(self, asset_id: str) -> Optional[AssetRecord]:
        """Retrieve asset record by ID, checking expiration"""
        with self._lock:
            record = self._assets.get(asset_id)
            if not record:
                return None
            
            # Check expiration
            if record.expires_at and datetime.now() > record.expires_at:
                logger.debug(f"Asset {asset_id} has expired")
                asset_key = _make_asset_key(record.filename, record.subfolder, record.folder_type)
                del self._assets[asset_id]
                if asset_key in self._asset_key_to_id:
                    del self._asset_key_to_id[asset_key]
                return None
            
            return record
    
    def get_asset_by_identity(
        self, filename: str, subfolder: str, folder_type: str
    ) -> Optional[AssetRecord]:
        """Get asset record by stable identity (filename, subfolder, type)."""
        with self._lock:
            asset_key = _make_asset_key(filename, subfolder, folder_type)
            asset_id = self._asset_key_to_id.get(asset_key)
            if not asset_id:
                return None
            
            return self.get_asset(asset_id)  # This will check expiration
    
    def list_assets(
        self, 
        limit: int = 10, 
        workflow_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> List[AssetRecord]:
        """List recent assets, optionally filtered by workflow_id and/or session_id.
        
        Returns assets sorted by creation time (newest first).
        
        Args:
            limit: Maximum number of assets to return
            workflow_id: Filter by workflow type (e.g., "generate_image")
            session_id: Filter by session ID (e.g., conversation ID)
        """
        with self._lock:
            # Cleanup expired first
            self.cleanup_expired()
            
            # Collect all assets
            assets = list(self._assets.values())
            
            # Filter by workflow_id if provided
            if workflow_id:
                assets = [a for a in assets if a.workflow_id == workflow_id]
            
            # Filter by session_id if provided
            if session_id:
                assets = [a for a in assets if a.session_id == session_id]
            
            # Sort by creation time (newest first)
            assets.sort(key=lambda a: a.created_at, reverse=True)
            
            # Apply limit
            return assets[:limit]
    
    def cleanup_expired(self):
        """Remove expired assets from registry"""
        with self._lock:
            now = datetime.now()
            expired_ids = [
                asset_id for asset_id, record in self._assets.items()
                if record.expires_at and now > record.expires_at
            ]
            
            for asset_id in expired_ids:
                record = self._assets[asset_id]
                asset_key = _make_asset_key(record.filename, record.subfolder, record.folder_type)
                del self._assets[asset_id]
                if asset_key in self._asset_key_to_id:
                    del self._asset_key_to_id[asset_key]
            
            if expired_ids:
                logger.info(f"Cleaned up {len(expired_ids)} expired assets")
            
            return len(expired_ids)
