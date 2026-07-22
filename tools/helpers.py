"""Shared helper functions for tool implementations"""

import logging
import os
from typing import Any, Dict, Optional

from asset_processor import encode_preview_for_mcp, fetch_asset_bytes, get_cache_key

logger = logging.getLogger("MCP_Server")


def register_and_build_response(
    result: Dict[str, Any],
    workflow_id: str,
    asset_registry,
    tool_name: Optional[str] = None,
    return_inline_preview: bool = False,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Helper function to register asset and build response data.

    Eliminates code duplication between run_workflow() and _register_workflow_tool().

    Args:
        result: Result dict from comfyui_client.run_custom_workflow()
        workflow_id: Workflow ID
        asset_registry: AssetRegistry instance
        tool_name: Optional tool name (for workflow-backed tools)
        return_inline_preview: Whether to include inline preview
        session_id: Optional session identifier for conversation filtering
        metadata: Optional extra metadata (e.g. prompt settings)

    Returns:
        Response data dict with asset_id, asset_url, metadata, etc.
        If the workflow is still running (timeout), returns a job handle dict instead.
    """
    # If the result is a "still running" job handle, add agent instructions and return
    if result.get("status") == "running":
        prompt_id = result.get("prompt_id", "")
        result["message"] = (
            f"Generation is currently running (prompt_id: '{prompt_id}'). "
            f"Please call get_job(prompt_id='{prompt_id}') to check status until status is 'completed'."
        )
        return result

    # Register asset in registry using stable identity
    asset_metadata = result.get("asset_metadata", {})
    record_metadata = {"workflow_id": workflow_id}
    if tool_name:
        record_metadata["tool"] = tool_name
    if metadata:
        record_metadata.update(metadata)
    
    asset_record = asset_registry.register_asset(
        filename=result.get("filename", ""),
        subfolder=result.get("subfolder", ""),
        folder_type=result.get("folder_type", "output"),
        workflow_id=workflow_id,
        prompt_id=result.get("prompt_id", ""),
        mime_type=asset_metadata.get("mime_type"),
        width=asset_metadata.get("width"),
        height=asset_metadata.get("height"),
        bytes_size=asset_metadata.get("bytes_size"),
        comfy_history=result.get("comfy_history"),
        submitted_workflow=result.get("submitted_workflow"),
        metadata=record_metadata,
        session_id=session_id
    )

    # Save local copy to COMFYUI_OUTPUT_ROOT if configured and fetch bytes
    output_root = os.getenv("COMFYUI_OUTPUT_ROOT")
    comfy_base = os.getenv("COMFYUI_URL", "http://localhost:8188").rstrip("/")
    direct_comfy_url = f"{comfy_base}/view?filename={asset_record.filename}&type={asset_record.folder_type}"
    if asset_record.subfolder:
        direct_comfy_url += f"&subfolder={asset_record.subfolder}"

    fetched_bytes = None
    if output_root and asset_record.filename:
        try:
            dest_dir = os.path.join(output_root, asset_record.subfolder) if asset_record.subfolder else output_root
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, asset_record.filename)
            
            # Legacy fallback: check if file was saved directly under output_root without subfolder
            flat_path = os.path.join(output_root, asset_record.filename)
            if not os.path.exists(dest_path) and os.path.exists(flat_path) and flat_path != dest_path:
                import shutil
                shutil.move(flat_path, dest_path)
                logger.info(f"Moved legacy asset from {flat_path} to subfolder path {dest_path}")

            if not os.path.exists(dest_path):
                fetched_bytes = fetch_asset_bytes(direct_comfy_url)
                with open(dest_path, "wb") as f:
                    f.write(fetched_bytes)
                logger.info(f"Saved generated asset to COMFYUI_OUTPUT_ROOT: {dest_path}")
            else:
                with open(dest_path, "rb") as f:
                    fetched_bytes = f.read()
        except Exception as e:
            logger.warning(f"Could not save copy to COMFYUI_OUTPUT_ROOT ({output_root}): {e}")

    # Build response data
    # Use asset_record.asset_url (computed from stable identity)
    asset_url = asset_record.asset_url or result.get("asset_url", "")
    response_data = {
        "status": "completed",
        "asset_id": asset_record.asset_id,
        "asset_url": asset_url,
        "image_url": asset_url,  # Backward compatibility
        "filename": asset_record.filename,  # Stable identity
        "subfolder": asset_record.subfolder,  # Stable identity
        "folder_type": asset_record.folder_type,  # Stable identity
        "workflow_id": workflow_id,
        "prompt_id": result.get("prompt_id"),
        "mime_type": asset_record.mime_type,
        "width": asset_record.width,
        "height": asset_record.height,
        "bytes_size": asset_record.bytes_size,
        "instructions": f"Display the image using Markdown embed syntax ![Generated Image]({asset_url}) AND provide an explicit clickable text link [Open / Download Image]({asset_url}) directly below it.",
    }
    
    if tool_name:
        response_data["tool"] = tool_name
    
    # Include inline preview if requested
    if return_inline_preview:
        try:
            # Only generate preview for images
            supported_types = ("image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif")
            if asset_record.mime_type in supported_types:
                if fetched_bytes is None:
                    fetched_bytes = fetch_asset_bytes(direct_comfy_url)
                cache_key = get_cache_key(asset_record.asset_id, 256, 70)
                encoded = encode_preview_for_mcp(
                    fetched_bytes,
                    max_dim=256,
                    max_b64_chars=100_000,  # ~100KB base64
                    quality=70,
                    cache_key=cache_key,
                )
                # Convert to data URI format for backward compatibility
                response_data["inline_preview_base64"] = f"data:{encoded.mime_type};base64,{encoded.b64}"
                response_data["inline_preview_mime_type"] = encoded.mime_type
        except Exception as e:
            logger.warning(f"Failed to generate inline preview: {e}")
            # Don't fail the request if preview generation fails
    
    # Include base64 image data if available (legacy)
    if "image_base64" in result:
        response_data["image_base64"] = result["image_base64"]
        response_data["image_mime_type"] = result.get("image_mime_type", "image/png")
    
    # Extract text analysis payloads (e.g. from PreviewAny / QwenVL vision nodes)
    raw_outputs = result.get("raw_outputs")
    if isinstance(raw_outputs, dict):
        text_outputs = []
        for node_id, node_out in raw_outputs.items():
            if isinstance(node_out, dict):
                for key in ("text", "string", "text_output"):
                    val = node_out.get(key)
                    if isinstance(val, list):
                        for item in val:
                            if isinstance(item, str) and item.strip():
                                text_outputs.append(item.strip())
                    elif isinstance(val, str) and val.strip():
                        text_outputs.append(val.strip())
        if text_outputs:
            analysis_text = "\n".join(text_outputs)
            response_data["analysis"] = analysis_text
            response_data["description"] = analysis_text

    return response_data
