"""Asset viewing tools for ComfyUI MCP Server"""

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP, Image as FastMCPImage
from asset_processor import (
    encode_preview_for_mcp,
    estimate_response_chars,
    fetch_asset_bytes,
    get_cache_key,
)

logger = logging.getLogger("MCP_Server")


def register_asset_tools(
    mcp: FastMCP,
    asset_registry
):
    """Register asset viewing tools with the MCP server (view_image disabled)"""
    pass
