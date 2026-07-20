"""
Test client for ComfyUI MCP Server using HTTP/JSON-RPC protocol.

This client connects to the MCP server using the streamable-http transport,
which uses standard HTTP requests with JSON-RPC protocol.
"""
import argparse
import json
import pprint
import sys
from typing import Any, Dict, Optional

import requests

# Configuration
MCP_ENDPOINT = "http://127.0.0.1:9000/mcp"
REQUEST_TIMEOUT = 300  # 5 minutes for long-running operations
REQUEST_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def parse_sse_response(response_text: str) -> dict:
    """Parse Server-Sent Events (SSE) response format."""
    lines = response_text.replace("\r\n", "\n").split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("data: "):
            json_str = line[6:]  # Remove "data: " prefix
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                continue
    raise ValueError("No valid JSON data found in SSE response")


def _make_request(method: str, params: Dict[str, Any], request_id: int = 1) -> Optional[dict]:
    """Make an MCP JSON-RPC request and return the parsed response."""
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }

    try:
        response = requests.post(
            MCP_ENDPOINT,
            json=request,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        # Handle both JSON and SSE responses
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            result = parse_sse_response(response.text)
        else:
            result = response.json()

        return result

    except requests.RequestException as e:
        print(f"Request error: {e}")
        if hasattr(e, "response") and e.response is not None:
            try:
                error_detail = e.response.json()
                print(f"Error details: {json.dumps(error_detail, indent=2)}")
            except Exception:
                print(f"Response text: {e.response.text[:500]}")
        return None

    except (ValueError, json.JSONDecodeError) as e:
        print(f"Error parsing response: {e}")
        if hasattr(e, "response"):
            print(f"Response text: {response.text[:500]}")
        return None


def list_available_tools() -> list:
    """List all available tools from the MCP server."""
    result = _make_request("tools/list", {})
    if not result:
        return []

    if "result" in result and "tools" in result["result"]:
        tools = result["result"]["tools"]
        print(f"\nAvailable tools ({len(tools)}):")
        for tool in tools:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "No description")
            # Extract first line/sentence for a one-liner summary
            one_liner = desc.split('\n')[0].strip()
            # Take first sentence if it ends with period, otherwise first 80 chars
            if '.' in one_liner:
                one_liner = one_liner.split('.')[0] + '.'
            if len(one_liner) > 80:
                one_liner = one_liner[:77] + "..."
            print(f"  • {name}: {one_liner}")
        return tools

    print("Unexpected response format:")
    print(json.dumps(result, indent=2))
    return []


def call_tool(tool_name: str, arguments: Dict[str, Any]) -> Optional[dict]:
    """Call an MCP tool with the given arguments."""
    print(f"\n  Calling tool '{tool_name}'")
    print(f"Arguments: {json.dumps(arguments, indent=2)}")

    result = _make_request("tools/call", {"name": tool_name, "arguments": arguments}, request_id=2)
    if not result:
        return None

    if "error" in result:
        print(f"\n[X] Error from server:")
        print(json.dumps(result["error"], indent=2))
        return None

    if "result" in result:
        result_data = result["result"]
        
        # Parse and replace JSON strings in text fields for cleaner display
        if "content" in result_data and isinstance(result_data["content"], list):
            for content_item in result_data["content"]:
                if isinstance(content_item, dict) and "text" in content_item:
                    text_content = content_item["text"]
                    try:
                        # Try to parse as JSON - if successful, replace text with parsed dict
                        parsed = json.loads(text_content)
                        content_item["text"] = parsed
                    except (json.JSONDecodeError, TypeError):
                        # If not JSON, just remove newlines for cleaner display
                        content_item["text"] = text_content.replace("\n", "").strip()
        
        print(f"\n[+] Response from server:")
        print(json.dumps(result_data, indent=2))
        
        # Handle nested content structure (MCP response format)
        # Response may have content array with text field containing JSON string
        if "content" in result_data and isinstance(result_data["content"], list) and len(result_data["content"]) > 0:
            first_content = result_data["content"][0]
            if isinstance(first_content, dict) and "text" in first_content:
                # If we already parsed it above, use that; otherwise try parsing
                if isinstance(first_content["text"], dict):
                    return first_content["text"]
                try:
                    parsed_text = json.loads(first_content["text"])
                    return parsed_text
                except (json.JSONDecodeError, TypeError):
                    # If parsing fails, fall through to return result_data as-is
                    pass
        
        # Return result_data directly if not in nested format
        return result_data

    print("\n[!]  Unexpected response format:")
    print(json.dumps(result, indent=2))
    return None


def print_section(title: str, width: int = 60):
    """Print a formatted section header."""
    print("\n" + "=" * width)
    print(title.center(width))
    print("=" * width)


def test_generate_image(prompt: Optional[str] = None):
    """Test the generate_image tool (if available)."""
    print_section("ComfyUI MCP Server Test Client")

    # List available tools
    print_section("Listing available tools...")
    tools = list_available_tools()

    if not tools:
        print("\n[X] No tools available. Make sure the server is running and workflows are loaded.")
        return

    # Find generate_image tool or use first available
    tool_name = None
    for tool in tools:
        if tool.get("name") == "text_image":
            tool_name = "text_image"
            break

    if not tool_name and tools:
        tool_name = tools[0].get("name")
        print(f"\n[!]  Using first available tool '{tool_name}' instead of 'generate_image'")

    if not tool_name:
        print("\n[X] No tools found to test.")
        return

    # Fetch server defaults
    print_section("Fetching server defaults...")
    defaults_result = call_tool("get_defaults", {})
    image_defaults = {}
    if defaults_result and "image" in defaults_result:
        image_defaults = defaults_result["image"]
        print(f"   Using server defaults: width={image_defaults.get('width', 'N/A')}, "
              f"height={image_defaults.get('height', 'N/A')}, "
              f"steps={image_defaults.get('steps', 'N/A')}, "
              f"model={image_defaults.get('model', 'N/A')}")
    else:
        print("   [!]  Could not fetch defaults, using fallback values")
        image_defaults = {"width": 512, "height": 512}

    # Call the tool
    print_section(f"Testing tool '{tool_name}'...")
    
    # Use provided prompt or default
    default_prompt = "an english mastiff dog, mouth closed, standing majestically in a grassy field, bright shiny day, forest background"
    prompt_to_use = prompt if prompt is not None else default_prompt
    
    # Build arguments - only include prompt (required), let server use defaults for the rest
    # The server will automatically apply defaults for width, height, steps, etc.
    arguments = {
        "prompt": prompt_to_use,
    }
    
    # Optionally, you could explicitly pass defaults if you want to show them:
    # arguments.update({
    #     "width": image_defaults.get("width"),
    #     "height": image_defaults.get("height"),
    #     "steps": image_defaults.get("steps"),
    #     "model": image_defaults.get("model"),
    # })

    result = call_tool(tool_name, arguments)

    # Display results
    print_section("Test Results")
    if result:
        print("[+] Test completed successfully!")
        
        # Extract URL (prefer asset_url, fallback to image_url)
        url = result.get("asset_url") or result.get("image_url")
        
        if url:
            print(f"\n  Generated asset URL: {url}")
            # Final one-line URL for easy selection/clicking
            print("\n" + "─" * 60)
            print(f"  View your image: {url}")
            print("─" * 60)
    else:
        print("[X] Test failed. Check the error messages above.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test client for ComfyUI MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_client.py
  python test_client.py -p "a beautiful sunset"
  python test_client.py --prompt "a cat on a mat"
        """
    )
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        default=None,
        help="Prompt text for image generation (can be used with or without quotes)"
    )
    
    args = parser.parse_args()
    
    try:
        test_generate_image(prompt=args.prompt)
    except KeyboardInterrupt:
        print("\n\n[!]  Test interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[X] Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
