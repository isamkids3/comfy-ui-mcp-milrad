"""ComfyUI MCP Server - Main entry point"""

import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import requests

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from comfyui_client import ComfyUIClient
from managers.asset_registry import AssetRegistry
from managers.defaults_manager import DefaultsManager
from managers.publish_manager import PublishConfig, PublishManager
from managers.workflow_manager import WorkflowManager
from tools.asset import register_asset_tools
from tools.configuration import register_configuration_tools
from tools.generation import register_workflow_generation_tools, register_regenerate_tool
from tools.job import register_job_tools
from tools.publish import register_publish_tools
from tools.upload import register_upload_tools
from tools.workflow import register_workflow_tools
from tools.document import register_document_tools
from async_comfyui_client import AsyncComfyUIClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MCP_Server")


def load_dotenv():
    """Load environment variables from a local .env file if it exists."""
    dotenv_path = Path(__file__).parent / ".env"
    if dotenv_path.exists():
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key:
                            os.environ.setdefault(key, val)
        except Exception as e:
            logger.warning(f"Failed to load .env file: {e}")


# Load environment variables
load_dotenv()

# Configuration paths
WORKFLOW_DIR = Path(os.getenv("COMFY_MCP_WORKFLOW_DIR", str(Path(__file__).parent / "workflows")))

# Asset registry configuration
ASSET_TTL_HOURS = int(os.getenv("COMFY_MCP_ASSET_TTL_HOURS", "24"))

# ComfyUI connection configuration
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188")
COMFYUI_MAX_RETRIES = 5  # Number of retry attempts
COMFYUI_INITIAL_DELAY = 2  # Initial delay in seconds
COMFYUI_MAX_DELAY = 16  # Maximum delay in seconds

# Publish configuration (optional env var for COMFYUI_OUTPUT_ROOT only)
COMFYUI_OUTPUT_ROOT = os.getenv("COMFYUI_OUTPUT_ROOT")


def print_startup_banner():
    """Print a nice startup banner for the server."""
    print("\n" + "=" * 70)
    print("[*] ComfyUI-MCP-Server".center(70))
    print("=" * 70)
    print(f"  Connecting to ComfyUI at: {COMFYUI_URL}")
    print(f"  Workflow directory: {WORKFLOW_DIR}")
    print(f"  Asset TTL: {ASSET_TTL_HOURS} hours")
    print("=" * 70 + "\n")


def check_comfyui_available(base_url: str) -> bool:
    """Check if ComfyUI is available by attempting to fetch model list.
    
    Returns True if ComfyUI is responding, False otherwise.
    """
    try:
        response = requests.get(f"{base_url}/object_info/CheckpointLoaderSimple", timeout=5)
        if response.status_code == 200:
            # Try to parse the response to ensure it's valid
            data = response.json()
            checkpoint_info = data.get("CheckpointLoaderSimple", {})
            if isinstance(checkpoint_info, dict):
                return True
        return False
    except (requests.RequestException, ValueError, KeyError):
        return False


def wait_for_comfyui(base_url: str, max_retries: int = COMFYUI_MAX_RETRIES, 
                     initial_delay: float = COMFYUI_INITIAL_DELAY,
                     max_delay: float = COMFYUI_MAX_DELAY) -> bool:
    """Wait for ComfyUI to become available with exponential backoff.
    
    Args:
        base_url: ComfyUI base URL
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay in seconds between retries
    
    Returns:
        True if ComfyUI becomes available, False if all retries exhausted
    """
    print("\n" + "=" * 70)
    print("[!]  ALERT: ComfyUI is not available!")
    print("=" * 70)
    print(f"  Checking for ComfyUI at: {base_url}")
    print(f"  Waiting for ComfyUI to start (will retry {max_retries} times)...")
    print("=" * 70 + "\n")
    
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        logger.info(f"ComfyUI availability check (attempt {attempt}/{max_retries})...")
        
        if check_comfyui_available(base_url):
            print("\n" + "=" * 70)
            print("[+] ComfyUI is now available!")
            print("=" * 70 + "\n")
            logger.info("ComfyUI is available, proceeding with server startup")
            return True
        
        if attempt < max_retries:
            print(f"[...] Attempt {attempt}/{max_retries} failed. Retrying in {delay:.1f} seconds...")
            time.sleep(delay)
            # Exponential backoff: double the delay, but cap at max_delay
            delay = min(delay * 2, max_delay)
        else:
            print(f"[X] Attempt {attempt}/{max_retries} failed. No more retries.")
    
    return False


# Print startup banner
print_startup_banner()

# Check ComfyUI availability before initializing clients unless explicitly skipped (e.g., in test environments)
if not os.getenv("COMFY_SKIP_HEALTHCHECK"):
    if not check_comfyui_available(COMFYUI_URL):
        if not wait_for_comfyui(COMFYUI_URL):
            print("\n" + "=" * 70)
            print("[X] ERROR: ComfyUI is not available after all retry attempts!")
            print("=" * 70)
            print(f"  Please ensure ComfyUI is running at: {COMFYUI_URL}")
            print("  Start ComfyUI first, then restart this server.")
            print("=" * 70 + "\n")
            sys.exit(1)

# Global ComfyUI client (fallback since context isn't available)
comfyui_client = ComfyUIClient(COMFYUI_URL)
async_comfyui_client = AsyncComfyUIClient(COMFYUI_URL)
workflow_manager = WorkflowManager(WORKFLOW_DIR)
defaults_manager = DefaultsManager(comfyui_client)
asset_registry = AssetRegistry(ttl_hours=ASSET_TTL_HOURS, comfyui_base_url=COMFYUI_URL)

# Publish manager (always initialized, uses auto-detection)
try:
    publish_config = PublishConfig(
        comfyui_output_root=COMFYUI_OUTPUT_ROOT,
        comfyui_url=COMFYUI_URL
    )
    publish_manager = PublishManager(publish_config)
    logger.info(f"Publish manager initialized with project_root={publish_config.project_root} (method: {publish_config.project_root_method})")
    logger.info(f"Publish root: {publish_config.publish_root}")
    if publish_config.comfyui_output_root:
        logger.info(f"ComfyUI output root: {publish_config.comfyui_output_root} (method: {publish_config.comfyui_output_method})")
    else:
        logger.info(f"ComfyUI output root: not configured (tried {len(publish_config.comfyui_tried_paths)} paths)")
except Exception as e:
    logger.warning(f"Failed to initialize publish manager: {e}. Publishing features may be unavailable.")
    # Still create a minimal manager so tools can register and return errors
    try:
        from managers.publish_manager import PublishConfig, PublishManager
        publish_config = PublishConfig(comfyui_url=COMFYUI_URL)
        publish_manager = PublishManager(publish_config)
    except Exception:
        publish_manager = None


# Define application context (for future use)
class AppContext:
    def __init__(self, comfyui_client: ComfyUIClient, async_client: AsyncComfyUIClient):
        self.comfyui_client = comfyui_client
        self.async_client = async_client


# Lifespan management (placeholder for future context support)
@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle"""
    logger.info("Starting MCP server lifecycle...")
    try:
        # Startup: Could add ComfyUI health check here in the future
        logger.info("ComfyUI client initialized globally")
        yield AppContext(comfyui_client=comfyui_client, async_client=async_comfyui_client)
    finally:
        # Shutdown: Cleanup (if needed)
        logger.info("Shutting down MCP server")


# Transport security configuration for DNS rebinding & origin validation
raw_origins = os.getenv("MCP_ALLOWED_ORIGINS")
raw_hosts = os.getenv("MCP_ALLOWED_HOSTS")

if raw_origins or raw_hosts:
    allowed_origins = [o.strip() for o in raw_origins.split(",")] if raw_origins else ["*"]
    allowed_hosts = [h.strip() for h in raw_hosts.split(",")] if raw_hosts else ["*"]
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )
else:
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    )

# Host & Port configuration
MCP_HOST = os.getenv("MCP_HOST", os.getenv("FASTMCP_HOST", "127.0.0.1"))
MCP_PORT = int(os.getenv("MCP_PORT", os.getenv("FASTMCP_PORT", "9000")))


class APIKeyAuthMiddleware:
    """ASGI Middleware enforcing HTTP Bearer token authentication."""

    def __init__(self, app, api_key: str | None = None):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            # Skip API key check for public static asset routes (/assets/*)
            if not path.startswith("/assets"):
                expected_key = self.api_key or os.getenv("MCP_API_KEY")
                if expected_key:
                    auth_header = None
                    for key, val in scope.get("headers", []):
                        if key.lower() == b"authorization":
                            auth_header = val.decode("utf-8")
                            break

                    if not auth_header or not auth_header.startswith("Bearer "):
                        # 401 Unauthorized for missing or malformed auth header
                        response_body = json.dumps({
                            "error": "Unauthorized",
                            "message": "Missing or invalid Authorization header. Expected 'Authorization: Bearer <MCP_API_KEY>'"
                        }).encode("utf-8")
                        await send({
                            "type": "http.response.start",
                            "status": 401,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"www-authenticate", b'Bearer realm="MCP"'),
                                (b"content-length", str(len(response_body)).encode("utf-8")),
                            ],
                        })
                        await send({
                            "type": "http.response.body",
                            "body": response_body,
                        })
                        return

                    token = auth_header[7:].strip()
                    if token != expected_key:
                        # 403 Forbidden for incorrect API key
                        response_body = json.dumps({
                            "error": "Forbidden",
                            "message": "Invalid API key"
                        }).encode("utf-8")
                        await send({
                            "type": "http.response.start",
                            "status": 403,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(response_body)).encode("utf-8")),
                            ],
                        })
                        await send({
                            "type": "http.response.body",
                            "body": response_body,
                        })
                        return

        await self.app(scope, receive, send)


def setup_ngrok_tunnel(port: int, authtoken: str | None = None, domain: str | None = None) -> str | None:
    """Start ngrok tunnel programmatically using pyngrok."""
    try:
        # pyrefly: ignore [missing-import]
        from pyngrok import ngrok
        if authtoken:
            ngrok.set_auth_token(authtoken)
        domain = domain or os.getenv("NGROK_DOMAIN")
        kwargs = {}
        if domain:
            kwargs["domain"] = domain
        tunnel = ngrok.connect(port, **kwargs)
        logger.info(f"Established ngrok tunnel: {tunnel.public_url}")
        return tunnel.public_url
    except Exception as e:
        logger.warning(f"Failed to start ngrok tunnel: {e}")
        return None


def run_streamable_http_server(mcp_server: FastMCP):
    """Run streamable-http transport wrapped with APIKeyAuthMiddleware and static asset routes."""
    import anyio
    import uvicorn
    from starlette.staticfiles import StaticFiles

    async def _run():
        starlette_app = mcp_server.streamable_http_app()

        # Mount static asset route if COMFYUI_OUTPUT_ROOT is configured and exists
        output_root = os.getenv("COMFYUI_OUTPUT_ROOT")
        if output_root and os.path.exists(output_root):
            logger.info(f"Mounting static asset endpoint /assets -> {output_root}")
            starlette_app.mount("/assets", StaticFiles(directory=output_root), name="assets")

        authenticated_app = APIKeyAuthMiddleware(starlette_app)

        config = uvicorn.Config(
            authenticated_app,
            host=mcp_server.settings.host,
            port=mcp_server.settings.port,
            log_level=mcp_server.settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()

    anyio.run(_run)


# Initialize FastMCP with lifespan, security, and port configuration
mcp = FastMCP(
    "ComfyUI_MCP_Server",
    instructions="When rendering generated images, always output both a Markdown image embed (![Image](url)) AND an explicit clickable text link ([Open Image](url)) below it.",
    lifespan=app_lifespan,
    host=MCP_HOST,
    port=MCP_PORT,
    stateless_http=True,
    transport_security=transport_security,
)

# Register all MCP tools
register_configuration_tools(mcp, comfyui_client, defaults_manager)
register_workflow_tools(mcp, workflow_manager, comfyui_client, defaults_manager, asset_registry)
register_asset_tools(mcp, asset_registry)
register_workflow_generation_tools(mcp, workflow_manager, comfyui_client, defaults_manager, asset_registry)
register_regenerate_tool(mcp, comfyui_client, asset_registry)
register_job_tools(mcp, comfyui_client, asset_registry)
register_upload_tools(mcp, comfyui_client)
register_document_tools(mcp)
# Always register publish tools (unconditional)
if publish_manager:
    register_publish_tools(mcp, asset_registry, publish_manager)
else:
    logger.error("Publish manager not available - publish tools will not be registered")

if __name__ == "__main__":
    # Check if running as MCP command (stdio) or standalone (streamable-http)
    # When run as command by MCP client (like Cursor), use stdio transport
    # When run standalone, use streamable-http for HTTP access
    if len(sys.argv) > 1 and sys.argv[1] == "--stdio":
        print("\n" + "=" * 70)
        print("[+] Server Ready".center(70))
        print("=" * 70)
        print(f"  Transport: stdio (for MCP clients)")
        print(f"[+] ComfyUI verified at: {COMFYUI_URL}")
        print("=" * 70 + "\n")
        logger.info("Starting MCP server with stdio transport (for MCP clients)")
        logger.info(f"ComfyUI verified at: {COMFYUI_URL}")
        try:
            mcp.run(transport="stdio")
        except KeyboardInterrupt:
            print("\n[*] Server stopped.")
    else:
        # Resolve public URL and ngrok tunnel setup
        public_url = os.getenv("MCP_PUBLIC_URL")
        enable_ngrok = os.getenv("ENABLE_NGROK", "false").lower() in ("true", "1", "yes")
        ngrok_token = os.getenv("NGROK_AUTHTOKEN")

        if not public_url and (enable_ngrok or ngrok_token):
            logger.info("Auto-starting built-in ngrok tunnel...")
            tunnel_url = setup_ngrok_tunnel(MCP_PORT, ngrok_token)
            if tunnel_url:
                public_url = tunnel_url

        if public_url:
            asset_registry.comfyui_base_url = public_url.rstrip("/")
            logger.info(f"Set AssetRegistry base URL to public endpoint: {public_url}")

        print("\n" + "=" * 70)
        print("[+] Server Ready".center(70))
        print("=" * 70)
        print(f"  Transport: streamable-http")
        print(f"  Local Endpoint: http://{MCP_HOST}:{MCP_PORT}/mcp")
        if public_url:
            print(f"  Public Endpoint: {public_url.rstrip('/')}/mcp")
            print(f"  Public Assets: {public_url.rstrip('/')}/assets/")
        if os.getenv("MCP_API_KEY"):
            print("  Authentication: Enabled (Bearer Token)")
        else:
            print("  Authentication: Disabled (MCP_API_KEY not set)")
        print(f"[+] ComfyUI verified at: {COMFYUI_URL}")
        print("=" * 70 + "\n")
        logger.info(f"Starting MCP server with streamable-http transport on http://{MCP_HOST}:{MCP_PORT}/mcp")
        logger.info(f"ComfyUI verified at: {COMFYUI_URL}")
        try:
            run_streamable_http_server(mcp)
        except KeyboardInterrupt:
            print("\n[*] Server stopped.")

