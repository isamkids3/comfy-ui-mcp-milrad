import aiohttp
import websockets
import json
import uuid
import asyncio
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger("AsyncComfyUIClient")

class AsyncComfyUIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        # Translate http/https to ws/wss
        if self.base_url.startswith("https://"):
            self.ws_url = "wss://" + self.base_url[len("https://"):]
        else:
            self.ws_url = "ws://" + self.base_url[len("http://"):]
            
    async def run_workflow(self, workflow: Dict[str, Any], max_attempts: int = 300) -> Dict[str, Any]:
        """
        Submit a workflow and wait for it to complete using WebSockets.
        """
        client_id = str(uuid.uuid4())
        ws_endpoint = f"{self.ws_url}/ws?clientId={client_id}"
        
        try:
            async with websockets.connect(ws_endpoint) as ws:
                # Submit workflow
                prompt_id = await self._queue_workflow(workflow, client_id)
                logger.info(f"Queued workflow with prompt_id: {prompt_id}")
                
                # Listen to websocket
                try:
                    await asyncio.wait_for(
                        self._listen_for_completion(ws, prompt_id), 
                        timeout=max_attempts
                    )
                    
                    # Fetch output details from history
                    history = await self.get_history(prompt_id)
                    prompt_data = history.get(prompt_id, {})
                    outputs = prompt_data.get("outputs", {})
                    
                    # Extract local file pointers
                    local_assets = self._extract_local_assets(outputs)
                    
                    return {
                        "prompt_id": prompt_id,
                        "status": "success",
                        "local_assets": local_assets,
                        "raw_outputs": outputs,
                        "submitted_workflow": workflow
                    }
                except asyncio.TimeoutError:
                    return {
                        "prompt_id": prompt_id,
                        "status": "timeout",
                        "message": f"Workflow timed out after {max_attempts}s"
                    }
                except Exception as e:
                    return {
                        "prompt_id": prompt_id,
                        "status": "error",
                        "error": str(e)
                    }
        except Exception as e:
            return {"status": "error", "error": f"WebSocket connection failed: {e}"}
                
    async def _listen_for_completion(self, ws, prompt_id: str):
        while True:
            msg = await ws.recv()
            if isinstance(msg, str):
                data = json.loads(msg)
                msg_type = data.get("type")
                msg_data = data.get("data", {})
                
                if msg_type == "execution_start" and msg_data.get("prompt_id") == prompt_id:
                    logger.info("Execution started")
                elif msg_type == "progress":
                    logger.info(f"Progress: {msg_data.get('value')}/{msg_data.get('max')}")
                elif msg_type == "executed" and msg_data.get("prompt_id") == prompt_id:
                    logger.info("Execution complete")
                    return True
                elif msg_type == "execution_error" and msg_data.get("prompt_id") == prompt_id:
                    raise Exception(f"Execution Error in node {msg_data.get('node_id')}: {msg_data.get('exception_type')}")
                    
    async def _queue_workflow(self, workflow: Dict[str, Any], client_id: str) -> str:
        logger.info(f"Dispatching workflow payload to ComfyUI server:\n{json.dumps(workflow, indent=2)}")
        async with aiohttp.ClientSession() as session:
            payload = {"prompt": workflow, "client_id": client_id}
            async with session.post(f"{self.base_url}/prompt", json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Failed to queue workflow: {resp.status} - {text}")
                data = await resp.json()
                prompt_id = data.get("prompt_id")
                if not prompt_id:
                    raise Exception("Response missing prompt_id")
                return prompt_id
                
    async def get_history(self, prompt_id: str) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/history/{prompt_id}") as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to get history: {resp.status}")
                return await resp.json()

    async def upload_image(self, image_path: str, overwrite: bool = True) -> Dict[str, str]:
        """Upload a local image file to ComfyUI input directory."""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found at {image_path}")
            
        filename = os.path.basename(image_path)
        
        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            data.add_field('image', open(image_path, 'rb'), filename=filename)
            data.add_field('overwrite', str(overwrite).lower())
            
            async with session.post(f"{self.base_url}/upload/image", data=data) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Upload failed: {resp.status} - {text}")
                return await resp.json()

    def _extract_local_assets(self, outputs: Dict[str, Any]) -> list:
        """Extract asset details to return proper file pointers"""
        assets = []
        for node_id, node_output in outputs.items():
            if not isinstance(node_output, dict):
                continue
            for key in ["images", "image", "gifs", "gif"]:
                items = node_output.get(key, [])
                for item in items:
                    if isinstance(item, dict) and "filename" in item:
                        # Construct a logical path pointer
                        assets.append({
                            "filename": item.get("filename"),
                            "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output")
                        })
        return assets
