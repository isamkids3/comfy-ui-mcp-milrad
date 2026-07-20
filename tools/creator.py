import os
import random
import logging
from typing import Dict, Any

from mcp.server.fastmcp import FastMCP
from async_comfyui_client import AsyncComfyUIClient

# Document parsing dependencies
try:
    import pypdf
except ImportError:
    pypdf = None
try:
    from docx import Document
except ImportError:
    Document = None

logger = logging.getLogger("CreatorAPI")

def register_creator_tools(mcp: FastMCP, async_client: AsyncComfyUIClient):
    """Register Layer 4 Creator API tools"""

    def generate_random_seed() -> int:
        return random.randint(0, 0xffffffffffffffff)
        
    def get_resolution_from_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
        # Simple mapping for common aspect ratios
        ratios = {
            "1:1": (1024, 1024),
            "16:9": (1344, 768),
            "9:16": (768, 1344),
            "4:3": (1152, 896),
            "3:4": (896, 1152)
        }
        return ratios.get(aspect_ratio, (1024, 1024))

    @mcp.tool()
    async def text_to_image(prompt: str, aspect_ratio: str) -> Dict[str, Any]:
        """
        TEXT-TO-IMAGE TOOL
        Compiles a standard text-guided generation JSON payload and routes it to the ComfyUI API.
        """
        width, height = get_resolution_from_aspect_ratio(aspect_ratio)
        seed = generate_random_seed()
        
        # Standard SDXL/SD1.5 compatible base workflow
        workflow = {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "cfg": 8,
                    "denoise": 1,
                    "latent_image": ["5", 0],
                    "model": ["4", 0],
                    "negative": ["7", 0],
                    "positive": ["6", 0],
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "seed": seed,
                    "steps": 20
                }
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": "v1-5-pruned-emaonly.ckpt" # Fallback, should be configured
                }
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "batch_size": 1,
                    "height": height,
                    "width": width
                }
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["4", 1],
                    "text": prompt
                }
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["4", 1],
                    "text": "text, watermark, ugly, deformed"
                }
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2]
                }
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": "mcp_txt2img",
                    "images": ["8", 0]
                }
            }
        }
        
        return await async_client.run_workflow(workflow)

    @mcp.tool()
    async def image_to_image(init_image_path: str, prompt: str, denoising_strength: float) -> Dict[str, Any]:
        """
        IMAGE-TO-IMAGE TOOL
        Compiles an Img2Img translation workflow for direct canvas manipulation based on the prompt instructions.
        """
        # 1. Upload the init image to ComfyUI
        upload_result = await async_client.upload_image(init_image_path)
        uploaded_filename = upload_result.get("name")
        
        seed = generate_random_seed()
        
        # Standard Img2Img workflow
        workflow = {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "cfg": 8,
                    "denoise": denoising_strength,
                    "latent_image": ["10", 0], # Output from VAEEncode
                    "model": ["4", 0],
                    "negative": ["7", 0],
                    "positive": ["6", 0],
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "seed": seed,
                    "steps": 20
                }
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": "v1-5-pruned-emaonly.ckpt"
                }
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["4", 1],
                    "text": prompt
                }
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["4", 1],
                    "text": "text, watermark, ugly, deformed"
                }
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2]
                }
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": "mcp_img2img",
                    "images": ["8", 0]
                }
            },
            "10": {
                "class_type": "VAEEncode",
                "inputs": {
                    "pixels": ["11", 0],
                    "vae": ["4", 2]
                }
            },
            "11": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": uploaded_filename
                }
            }
        }
        
        return await async_client.run_workflow(workflow)

    @mcp.tool()
    async def image_reference_and_text_to_image(prompt: str, reference_image_path: str, strength: float) -> Dict[str, Any]:
        """
        IMAGE REFERENCE + TEXT-TO-IMAGE TOOL
        Implements reference-guided generative strategy using ControlNet.
        """
        # Upload the reference image
        upload_result = await async_client.upload_image(reference_image_path)
        uploaded_filename = upload_result.get("name")
        
        seed = generate_random_seed()
        
        # Workflow with ControlNet integration
        workflow = {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "cfg": 8,
                    "denoise": 1,
                    "latent_image": ["5", 0],
                    "model": ["4", 0],
                    "negative": ["7", 0],
                    "positive": ["13", 0], # Output from ControlNetApply
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "seed": seed,
                    "steps": 20
                }
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": "v1-5-pruned-emaonly.ckpt"
                }
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "batch_size": 1,
                    "height": 1024,
                    "width": 1024
                }
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["4", 1],
                    "text": prompt
                }
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["4", 1],
                    "text": "text, watermark, ugly, deformed"
                }
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2]
                }
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": "mcp_ref2img",
                    "images": ["8", 0]
                }
            },
            "11": {
                "class_type": "LoadImage",
                "inputs": {
                    "image": uploaded_filename
                }
            },
            "12": {
                "class_type": "ControlNetLoader",
                "inputs": {
                    "control_net_name": "control_v11p_sd15_canny.pth" # Fallback CN model
                }
            },
            "13": {
                "class_type": "ControlNetApply",
                "inputs": {
                    "conditioning": ["6", 0],
                    "control_net": ["12", 0],
                    "image": ["11", 0],
                    "strength": strength
                }
            }
        }
        
        return await async_client.run_workflow(workflow)

    @mcp.tool()
    def read_user_document(file_path: str) -> str:
        """
        USER DOCUMENT INGESTION TOOL
        Parses and extracts text content from local user uploads (.txt, .pdf, or .docx) inside the sandbox workspace, returning clean string payloads.
        """
        if not os.path.exists(file_path):
            return f"Error: File not found at {file_path}"
            
        ext = os.path.splitext(file_path)[1].lower()
        
        try:
            if ext == '.txt':
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            elif ext == '.pdf':
                if pypdf is None:
                    return "Error: pypdf library is not installed."
                text = []
                with open(file_path, 'rb') as f:
                    reader = pypdf.PdfReader(f)
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text.append(page_text)
                return "\n".join(text)
            elif ext == '.docx':
                if Document is None:
                    return "Error: python-docx library is not installed."
                doc = Document(file_path)
                text = [para.text for para in doc.paragraphs]
                return "\n".join(text)
            else:
                return f"Error: Unsupported file extension '{ext}'. Only .txt, .pdf, and .docx are supported."
        except Exception as e:
            logger.error(f"Failed to read document {file_path}: {e}")
            return f"Error reading document: {e}"
