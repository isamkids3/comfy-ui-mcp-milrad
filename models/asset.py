"""Asset data models"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote


@dataclass
class AssetRecord:
    """Record of a generated asset for tracking and viewing.
    
    Uses (filename, subfolder, type) as stable identity instead of URL,
    making the system robust to URL changes (e.g., different hostnames).
    """
    asset_id: str
    filename: str  # Stable identity: filename
    subfolder: str  # Stable identity: subfolder (often empty)
    folder_type: str  # Stable identity: type (usually "output")
    prompt_id: str  # Link to ComfyUI history
    workflow_id: str
    created_at: datetime
    expires_at: Optional[datetime]
    
    # Presentation/display fields
    mime_type: str
    width: Optional[int]
    height: Optional[int]
    bytes_size: int
    sha256: Optional[str]  # Content hash for deduplication
    
    # ComfyUI history snapshot (full /history/{prompt_id} response)
    comfy_history: Optional[Dict[str, Any]] = field(default=None)
    # Original submitted workflow (for provenance)
    submitted_workflow: Optional[Dict[str, Any]] = field(default=None)
    
    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Session tracking for conversation isolation
    session_id: Optional[str] = None
    
    def get_asset_url(self, base_url: str) -> str:
        """Get asset URL for a given base URL.
        
        Handles URL encoding for special characters in filenames and subfolders.
        Also normalizes base_url (removes trailing slashes).
        """
        # Normalize base_url (remove trailing slash)
        base_url = base_url.rstrip('/')
        
        # URL encode filename and subfolder to handle special characters
        encoded_filename = quote(self.filename, safe='')
        encoded_subfolder = quote(self.subfolder, safe='') if self.subfolder else ''
        
        # If base_url is an MCP server URL (not direct ComfyUI port 8188 or containing /assets),
        # use the /assets static endpoint
        if "/assets" in base_url or not (":8188" in base_url or base_url.endswith("/view")):
            if encoded_subfolder:
                return f"{base_url}/assets/{encoded_subfolder}/{encoded_filename}"
            else:
                return f"{base_url}/assets/{encoded_filename}"
        
        # Build ComfyUI direct URL with proper encoding
        if encoded_subfolder:
            return f"{base_url}/view?filename={encoded_filename}&subfolder={encoded_subfolder}&type={self.folder_type}"
        else:
            return f"{base_url}/view?filename={encoded_filename}&type={self.folder_type}"
    
    @property
    def asset_url(self) -> str:
        """Compute asset URL on-the-fly from stable identity.
        
        Note: This requires the base URL to be stored. The registry
        sets this via _base_url attribute. Falls back to empty string
        if base URL not available.
        """
        base_url = getattr(self, '_base_url', None)
        if base_url:
            return self.get_asset_url(base_url)
        return ""
    
    def set_base_url(self, base_url: str):
        """Set the ComfyUI base URL for computing asset URLs."""
        self._base_url = base_url
