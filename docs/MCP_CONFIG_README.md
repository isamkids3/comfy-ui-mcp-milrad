# MCP Configuration for Cursor

This file explains how to configure Cursor to connect to the ComfyUI MCP Server. For general usage instructions, see [README.md](README.md).

## Two Connection Methods

Cursor supports two ways to connect to the MCP server:

### Option 1: HTTP-based Connection (Recommended)

Cursor connects to a running server via HTTP. This allows the server to run independently and be accessed by multiple clients.

**Configuration:**
```json
{
  "mcpServers": {
    "comfyui-mcp-server": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:9000/mcp"
    }
  }
}
```

**Steps:**
1. Start the MCP server manually:
   ```bash
   python server.py
   ```
   The server will start on `http://127.0.0.1:9000/mcp`

2. Add the configuration above to Cursor's MCP config file

3. Restart Cursor

### Option 2: Command-based Connection (stdio)

Cursor automatically starts and manages the server process. No manual server startup required.

**Configuration:**
```json
{
  "mcpServers": {
    "comfyui-mcp-server": {
      "command": "python",
      "args": [
        "/path/to/comfyui-mcp-server/server.py",
        "--stdio"
      ],
      "env": {
        "COMFYUI_URL": "http://localhost:8188"
      }
    }
  }
}
```

**Important Notes:**
- **Update the Path**: Replace `/path/to/comfyui-mcp-server/server.py` with your actual absolute path:
  - Windows: `"E:\\dev\\comfyui-mcp-server\\server.py"`
  - Mac/Linux: `"/path/to/comfyui-mcp-server/server.py"`
- **Python Command**: You may need to use `python3` on Mac/Linux, or the full path to your Python executable
- **ComfyUI URL**: The `COMFYUI_URL` environment variable should point to your ComfyUI instance (default: `http://localhost:8188`)

**Steps:**
1. Add the configuration above to Cursor's MCP config file (with your actual path)
2. Restart Cursor (the server will start automatically)

## Locating Cursor's MCP Config

The MCP configuration file location varies by platform. Check Cursor's settings or documentation for the exact location on your system.

## Verifying Connection

After restarting Cursor:
- Cursor should show the ComfyUI MCP server as available
- You should see tools like `generate_image` and `generate_song` available

## Available Tools

Once connected, you'll have access to all MCP tools. See [README.md](README.md#available-tools) for the complete list, including:

- **generate_image**: Generate images using ComfyUI
- **generate_song**: Generate audio/songs using ComfyUI
- **regenerate**: Regenerate existing assets with parameter overrides
- **view_image**: View generated images inline
- **get_job**, **get_queue_status**, **cancel_job**: Job management
- **list_assets**, **get_asset_metadata**: Asset browsing
- **set_defaults**, **get_defaults**: Configuration management

## Troubleshooting

### Server Not Connecting (HTTP-based)

1. **Check Server is Running**: Make sure you've started the server with `python server.py`
2. **Check Port**: Verify the server is listening on `http://127.0.0.1:9000/mcp`
3. **Check ComfyUI**: Ensure ComfyUI is running on the configured port (default: 8188)

### Server Not Starting (Command-based)

1. **Check Python Path**: Make sure `python` in the command is the correct Python interpreter
   - You might need to use `python3` on Mac/Linux
   - Or use the full path: `"C:\\Python\\python.exe"` (Windows) or `"/usr/bin/python3"` (Mac/Linux)

2. **Check Server Path**: Verify the path to `server.py` is correct and absolute

3. **Check Dependencies**: Ensure all Python dependencies are installed:
   ```bash
   pip install -r requirements.txt
   ```

4. **Check ComfyUI**: Make sure ComfyUI is running on the configured port (default: 8188)

### Tools Not Appearing

1. **Check Workflows**: Ensure workflow files exist in the `workflows/` directory
2. **Check Logs**: Look at Cursor's logs or server output for errors
3. **Verify Workflow Format**: Workflows must contain `PARAM_*` placeholders to be auto-discovered

### General Issues

- **Transport Type**: Make sure you're using `"type": "streamable-http"` (not `"http"`) for HTTP-based connections
- **Path Format**: Use forward slashes or escaped backslashes in JSON paths (Windows: `"E:\\dev\\..."` or `"E:/dev/..."`)
- **Restart Required**: Always restart Cursor after changing MCP configuration
