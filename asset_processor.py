"""Image processing utilities for asset viewing and thumbnail generation"""

import base64
import logging
import os
import requests
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, Any, Optional, Tuple, Union

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logging.warning("Pillow not available. Image processing features will be limited.")

logger = logging.getLogger("AssetProcessor")

# Simple in-memory cache for processed previews
_preview_cache: Dict[str, "EncodedImage"] = {}


def fetch_asset_bytes(asset_url: str, timeout: int = 30) -> bytes:
    """Fetch asset bytes from ComfyUI /view endpoint"""
    try:
        response = requests.get(asset_url, timeout=timeout)
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        logger.error(f"Failed to fetch asset from {asset_url}: {e}")
        raise


def get_image_metadata(image_bytes: bytes) -> Dict[str, Any]:
    """Extract width, height, format from image bytes"""
    if not PIL_AVAILABLE:
        return {"width": None, "height": None, "format": None}
    
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            return {
                "width": img.width,
                "height": img.height,
                "format": img.format
            }
    except Exception as e:
        logger.warning(f"Failed to extract image metadata: {e}")
        return {"width": None, "height": None, "format": None}


def should_downscale(width: int, height: int, max_dim: int) -> bool:
    """Determine if image needs downscaling"""
    return width > max_dim or height > max_dim


def create_thumbnail(
    image_bytes: bytes,
    max_dim: int = 512,
    quality: int = 75,
    format: str = "JPEG"
) -> bytes:
    """Create downscaled thumbnail, re-encode as JPEG"""
    if not PIL_AVAILABLE:
        raise ImportError("Pillow is required for image processing")
    
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            # Convert to RGB if necessary (for JPEG)
            if img.mode in ("RGBA", "LA", "P"):
                # Create white background for transparency
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")
            
            # Calculate new dimensions
            width, height = img.size
            if width > max_dim or height > max_dim:
                if width > height:
                    new_width = max_dim
                    new_height = int(height * (max_dim / width))
                else:
                    new_height = max_dim
                    new_width = int(width * (max_dim / height))
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Save to bytes
            output = BytesIO()
            img.save(output, format=format, quality=quality, optimize=True)
            return output.getvalue()
    except Exception as e:
        logger.error(f"Failed to create thumbnail: {e}")
        raise


def strip_metadata(image_bytes: bytes) -> bytes:
    """Remove EXIF and other metadata chunks"""
    if not PIL_AVAILABLE:
        return image_bytes
    
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            # Create new image without metadata
            data = list(img.getdata())
            image_without_exif = Image.new(img.mode, img.size)
            image_without_exif.putdata(data)
            
            # Save to bytes
            output = BytesIO()
            # Preserve format if possible
            format = img.format or "JPEG"
            if format == "PNG":
                image_without_exif.save(output, format="PNG", optimize=True)
            else:
                image_without_exif.save(output, format="JPEG", quality=95, optimize=True)
            return output.getvalue()
    except Exception as e:
        logger.warning(f"Failed to strip metadata, returning original: {e}")
        return image_bytes


@dataclass(frozen=True)
class EncodedImage:
    """Encoded image result with all metrics"""
    b64: str  # Base64 string (without data URI prefix)
    mime_type: str  # image/webp
    size_px: Tuple[int, int]  # Final dimensions
    bytes_len: int  # Raw byte size before base64
    b64_chars: int  # Base64 character count (what matters for serialized response)
    raw_bytes: bytes  # Raw encoded bytes (for FastMCP.Image)


def get_cache_key(asset_id: str, max_dim: int, quality: int) -> str:
    """Generate cache key for processed preview"""
    return f"{asset_id}:{max_dim}:webp:{quality}"


def _get_cached_preview(cache_key: str) -> Optional[EncodedImage]:
    """Get cached preview if available"""
    return _preview_cache.get(cache_key)


def _cache_preview(cache_key: str, encoded: EncodedImage):
    """Cache processed preview (simple LRU: keep last 100 entries)"""
    if len(_preview_cache) > 100:
        _preview_cache.pop(next(iter(_preview_cache)))
    _preview_cache[cache_key] = encoded


def estimate_response_chars(b64_chars: int, json_overhead: int = 200) -> int:
    """Estimate total serialized response size (for logging/debugging)"""
    # Rough estimate: base64 + JSON structure + surrounding text
    return b64_chars + json_overhead


def mcp_image_content(encoded: EncodedImage) -> dict:
    """Convert EncodedImage to MCP ImageContent structure"""
    # MCP ImageContent expects data URI format: "data:image/webp;base64,<base64>"
    return {
        "type": "image",
        "data": f"data:{encoded.mime_type};base64,{encoded.b64}",
        "mimeType": encoded.mime_type,
    }


def encode_preview_for_mcp(
    image_source: Union[str, bytes, BytesIO],
    *,
    max_dim: int = 512,
    max_b64_chars: int = 100_000,  # Base64 character budget (100KB - conservative to prevent hangs)
    quality: int = 70,
    strip_metadata: bool = True,
    cache_key: Optional[str] = None,
) -> EncodedImage:
    """
    Loads an image, downscales, re-encodes to WebP, enforces base64 budget, returns base64.
    Designed for MCP tool responses where serialized payload size matters.
    
    Enforces budget on base64 character count (what Cursor actually sees), not raw bytes.
    Uses deterministic quality/downscale ladder for predictable behavior.
    
    Args:
        image_source: URL (str), file path (str), bytes, or BytesIO
        max_dim: Maximum dimension in pixels (default: 512, hard cap)
        max_b64_chars: Maximum base64 character count (default: 100000, ~100KB - conservative)
        quality: Starting quality level (default: 70)
        strip_metadata: Remove EXIF/metadata (default: True)
        cache_key: Optional cache key for result caching
    
    Returns:
        EncodedImage with base64, mime_type, dimensions, and metrics
    
    Raises:
        ValueError: If image still exceeds budget after all optimizations
        ImportError: If Pillow is not available
    """
    if not PIL_AVAILABLE:
        raise ImportError("Pillow is required for image processing. Install with: pip install Pillow")
    
    # Check cache first
    if cache_key:
        cached = _get_cached_preview(cache_key)
        if cached:
            logger.debug(f"Cache hit for {cache_key}")
            return cached
    
    # Load image from various sources and track source size
    src_bytes = 0
    if isinstance(image_source, str):
        # URL or file path
        if image_source.startswith(("http://", "https://")):
            image_bytes = fetch_asset_bytes(image_source)
            src_bytes = len(image_bytes)
            img_source = BytesIO(image_bytes)
        else:
            # File path
            if not os.path.exists(image_source):
                raise FileNotFoundError(image_source)
            src_bytes = os.path.getsize(image_source)
            img_source = image_source
    elif isinstance(image_source, bytes):
        src_bytes = len(image_source)
        img_source = BytesIO(image_source)
    else:
        # Already BytesIO - can't get size easily, will be 0
        img_source = image_source
    
    # Track source dimensions for logging
    src_w, src_h = 0, 0
    
    # Load and normalize image
    with Image.open(img_source) as loaded_im:
        # Apply EXIF orientation correction (returns new Image object)
        im = ImageOps.exif_transpose(loaded_im)
        src_w, src_h = im.size
        
        # WebP alpha handling: keep alpha for WebP, flatten for JPEG (if we add it later)
        # For now, WebP only - keep alpha if present
        if im.mode in ("RGBA", "LA"):
            # Keep alpha for WebP
            pass
        elif im.mode not in ("RGB", "L"):
            # Convert other modes to RGB (returns new Image object)
            im = im.convert("RGB")
    
    # Deterministic quality/downscale ladder
    # Quality levels to try: [70, 55, 40]
    # Downscale targets: [max_dim, 384, 256] (if needed)
    quality_levels = [quality, 55, 40]
    downscale_targets = [max_dim, 384, 256]
    
    final_encoded = None
    final_q = None
    final_dim = None
    
    for downscale_target in downscale_targets:
        # Downscale to target (maintain aspect ratio)
        w, h = im.size
        if max(w, h) > downscale_target:
            scale = min(1.0, downscale_target / max(w, h))
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            im_resized = im.resize(new_size, Image.Resampling.LANCZOS)
        else:
            im_resized = im
        
        # Try quality levels
        for q in quality_levels:
            buf = BytesIO()
            
            # Save as WebP
            save_kwargs = {
                "format": "WEBP",
                "quality": q,
                "method": 5,  # Method 5 trades CPU for size (good balance)
            }
            
            # Preserve alpha for WebP if present
            if im_resized.mode in ("RGBA", "LA"):
                save_kwargs["lossless"] = False  # Use lossy compression
            
            im_resized.save(buf, **save_kwargs)
            encoded_bytes = buf.getvalue()
            b64_string = base64.b64encode(encoded_bytes).decode("ascii")
            b64_chars = len(b64_string)
            
            # Account for data URI prefix in budget check
            # "data:image/webp;base64," adds ~23 chars
            data_uri_prefix_len = len("data:image/webp;base64,")
            total_payload_chars = b64_chars + data_uri_prefix_len
            
            # Check if within budget (including prefix)
            if total_payload_chars <= max_b64_chars:
                final_encoded = encoded_bytes
                final_q = q
                final_dim = im_resized.size
                break
        
        if final_encoded is not None:
            break
    
    # If still too large, refuse to inline
    if final_encoded is None:
        # Last attempt: try smallest size with lowest quality
        w, h = im.size
        smallest_dim = 256
        if max(w, h) > smallest_dim:
            scale = min(1.0, smallest_dim / max(w, h))
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            im_resized = im.resize(new_size, Image.Resampling.LANCZOS)
        else:
            im_resized = im
        
        buf = BytesIO()
        im_resized.save(buf, format="WEBP", quality=35, method=5)
        encoded_bytes = buf.getvalue()
        b64_string = base64.b64encode(encoded_bytes).decode("ascii")
        b64_chars = len(b64_string)
        
        # Account for data URI prefix
        data_uri_prefix_len = len("data:image/webp;base64,")
        total_payload_chars = b64_chars + data_uri_prefix_len
        
        if total_payload_chars <= max_b64_chars:
            final_encoded = encoded_bytes
            final_q = 35
            final_dim = im_resized.size
        else:
            # Refuse to inline - exceeds budget even at minimum settings
            raise ValueError(
                f"Image exceeds base64 budget: {b64_chars} chars > {max_b64_chars} chars "
                f"(even at {smallest_dim}px, quality=35). Refusing to inline."
            )
    
    # Create result
    b64_string = base64.b64encode(final_encoded).decode("ascii")
    b64_chars = len(b64_string)
    
    # Account for data URI prefix in final payload size
    # "data:image/webp;base64," adds ~23 chars, so check total payload
    data_uri_prefix_len = len(f"data:image/webp;base64,")
    total_payload_chars = b64_chars + data_uri_prefix_len
    
    # If total payload exceeds budget, refuse to inline
    if total_payload_chars > max_b64_chars:
        raise ValueError(
            f"Image exceeds base64 budget: total payload {total_payload_chars} chars > {max_b64_chars} chars "
            f"(base64: {b64_chars} chars + prefix: {data_uri_prefix_len} chars). Refusing to inline."
        )
    
    result = EncodedImage(
        b64=b64_string,
        mime_type="image/webp",
        size_px=final_dim,
        bytes_len=len(final_encoded),
        b64_chars=b64_chars,
        raw_bytes=final_encoded,  # Raw bytes for FastMCP.Image
    )
    
    # Cache result
    if cache_key:
        _cache_preview(cache_key, result)
    
    # Log telemetry
    logger.info(
        f"view_asset encoding: src={src_bytes}B src_dims={src_w}x{src_h} "
        f"preview_dims={final_dim[0]}x{final_dim[1]} format=webp quality={final_q} "
        f"encoded={len(final_encoded)}B b64_chars={b64_chars} total_payload={total_payload_chars} "
        f"response_est={estimate_response_chars(total_payload_chars)}chars"
    )
    
    return result

