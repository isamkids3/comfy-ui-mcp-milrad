"""Upload tools for sending reference images to ComfyUI"""

import base64
import logging
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("MCP_Server")


def register_upload_tools(mcp: FastMCP, comfyui_client):
    """Register image upload tools for IP-Adapter and other image-input workflows."""

    @mcp.tool()
    def upload_reference_image(
        image_base64: str,
        filename: str = "reference.png",
        subfolder: str = "",
        overwrite: bool = True,
    ) -> dict:
        """Upload a reference image to ComfyUI for use with IP-Adapter styled image generation.

        The image is uploaded to ComfyUI's input directory so it can be referenced
        by workflows that use LoadImage nodes (e.g., generate_styled_image).

        Args:
            image_base64: Base64-encoded image data. Can optionally include a
                          data URI prefix (e.g., 'data:image/png;base64,...')
                          which will be stripped automatically.
            filename: Desired filename for the uploaded image (e.g., 'my_ref.png').
                      ComfyUI may rename the file if it already exists and
                      overwrite is False.
            subfolder: Optional subfolder within ComfyUI's input directory.
            overwrite: If True, overwrites existing files with the same name.

        Returns:
            dict: Upload result with keys:
                - filename: The actual stored filename (use this in generate_styled_image)
                - subfolder: Subfolder where the file was stored
                - type: Always "input"
                - status: "uploaded"

        Example:
            # Step 1: Upload
            result = upload_reference_image(
                image_base64="iVBORw0KGgo...",
                filename="sunset_ref.png"
            )
            # Step 2: Generate
            generate_styled_image(
                prompt="a castle on a hill, golden hour, cinematic",
                reference_image=result["filename"]
            )
        """
        try:
            # Strip data URI prefix if present
            if "," in image_base64 and image_base64.startswith("data:"):
                image_base64 = image_base64.split(",", 1)[1]

            # Strip any whitespace/newlines that may be in the base64 string
            image_base64 = image_base64.strip().replace("\n", "").replace("\r", "")

            # Decode base64 to bytes
            try:
                image_bytes = base64.b64decode(image_base64)
            except Exception as e:
                return {"error": f"Invalid base64 data: {e}"}

            if len(image_bytes) == 0:
                return {"error": "Decoded image is empty (0 bytes)"}

            # Validate it looks like an image (check magic bytes)
            if not _is_valid_image(image_bytes):
                return {
                    "error": "Decoded data does not appear to be a valid image. "
                    "Supported formats: PNG, JPEG, WebP, BMP, GIF."
                }

            # Sanitize filename
            safe_filename = _sanitize_filename(filename)
            if not safe_filename:
                return {"error": f"Invalid filename: {filename}"}

            # Upload to ComfyUI
            result = comfyui_client.upload_image(
                image_bytes=image_bytes,
                filename=safe_filename,
                subfolder=subfolder,
                overwrite=overwrite,
            )

            logger.info(
                "Uploaded reference image: %s (%d bytes)",
                result.get("name", safe_filename),
                len(image_bytes),
            )

            return {
                "filename": result.get("name", safe_filename),
                "subfolder": result.get("subfolder", subfolder),
                "type": result.get("type", "input"),
                "status": "uploaded",
                "bytes_size": len(image_bytes),
            }

        except Exception as e:
            logger.exception("Failed to upload reference image")
            return {"error": f"Upload failed: {str(e)}"}


def _is_valid_image(data: bytes) -> bool:
    """Check if bytes data starts with a known image magic number."""
    if len(data) < 4:
        return False
    # PNG
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    # JPEG
    if data[:2] == b"\xff\xd8":
        return True
    # WebP
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return True
    # BMP
    if data[:2] == b"BM":
        return True
    # GIF
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    return False


def _sanitize_filename(filename: str) -> Optional[str]:
    """Sanitize filename to prevent path traversal and ensure valid extension."""
    if not filename:
        return None

    # Strip any directory components
    filename = os.path.basename(filename)

    # Remove dangerous characters
    safe_chars = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    )
    filename = "".join(c for c in filename if c in safe_chars)

    if not filename or filename.startswith("."):
        return None

    # Ensure it has a valid image extension
    valid_extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
    _, ext = os.path.splitext(filename)
    if ext.lower() not in valid_extensions:
        filename += ".png"

    return filename
