# Docker Compose & Cloudflare Tunnel Setup Guide

This guide explains how to deploy the **ComfyUI MCP Server** using **Docker Compose** and **Cloudflare Tunnel (`cloudflared`)**.

---

## Overview

In this deployment architecture:
1. **ComfyUI**: Runs natively on the host machine (e.g. PGX) at `http://localhost:8188` or local LAN IP.
2. **`mcp-server` Container**: Runs the Python MCP server, connects to ComfyUI via `host.docker.internal:8188`, and mounts the output directory specified in `COMFYUI_OUTPUT_ROOT`.
3. **`cloudflared` Container**: Exposes `mcp-server:9000` to the internet securely via Cloudflare Zero Trust without opening router ports or using ngrok.

---

## Step 1: Create a Cloudflare Tunnel

1. Log into your [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/).
2. Go to **Networks** -> **Tunnels** -> **Create a Tunnel**.
3. Select **Cloudflared** as the connector type and name your tunnel (e.g., `comfyui-mcp-tunnel`).
4. Copy the generated **Tunnel Token** (the long string following `--token`).
5. Under **Public Hostnames**:
   - **Subdomain / Domain**: Enter your public domain (e.g., `mcp.yourdomain.com`).
   - **Type**: `HTTP`
   - **URL**: `mcp-server:9000` (this resolves to the `mcp-server` container inside the Docker network).

---

## Step 2: Configure `.env`

Copy `.env.example` to `.env` or edit your existing `.env`:

```ini
# ComfyUI Connection (Running natively on PGX host)
COMFYUI_URL=http://host.docker.internal:8188

# Storage Directory for Generated Images/Videos on Host
COMFYUI_OUTPUT_ROOT=/Users/adamdali/Documents/Millenium Radius/mcp_images

# MCP Security
MCP_API_KEY=your-secret-bearer-token

# Binding (0.0.0.0 required for container listening)
MCP_HOST=0.0.0.0
MCP_PORT=9000

# Cloudflare Tunnel Configuration
CLOUDFLARE_TUNNEL_TOKEN=eyJhY...your_token_here...
MCP_PUBLIC_URL=https://mcp.yourdomain.com
```

---

## Step 3: Run with Docker Compose

Start the services in detached mode:

```bash
docker compose up -d --build
```

### Checking Logs & Status

- View all running containers:
  ```bash
  docker compose ps
  ```

- Stream MCP server logs:
  ```bash
  docker compose logs -f mcp-server
  ```

- Stream Cloudflare tunnel logs:
  ```bash
  docker compose logs -f cloudflared
  ```

- Stop the services:
  ```bash
  docker compose down
  ```

---

## Connecting MCP Clients (Claude, Cursor, etc.)

In your MCP client configuration (`.mcp.json` or Cursor Settings):

```json
{
  "mcpServers": {
    "comfyui-mcp": {
      "serverUrl": "https://mcp.yourdomain.com/mcp",
      "headers": {
        "Authorization": "Bearer your-secret-bearer-token"
      }
    }
  }
}
```

---

## Troubleshooting

- **Cannot connect to ComfyUI (`Connection Refused`)**:
  - Ensure ComfyUI is running on the host machine.
  - Verify `COMFYUI_URL=http://host.docker.internal:8188` or use your PGX LAN IP (e.g. `http://192.168.x.x:8188`).
  - Make sure `listen_address` in ComfyUI is set to `0.0.0.0` or allows connections from Docker.

- **Images/Videos not saving to host**:
  - Check that `COMFYUI_OUTPUT_ROOT` in `.env` points to a valid writable directory on your host.
