#!/usr/bin/env python3
"""
Test script to trigger ComfyUI workflows and verify generation works.
"""
import argparse
import sys
import os
from pathlib import Path
import requests

# Add current directory to path just in case
sys.path.append(str(Path(__file__).parent.resolve()))

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
                            os.environ[key] = val
        except Exception as e:
            print(f"Warning: Failed to load .env file: {e}")

load_dotenv()

try:
    from comfyui_client import ComfyUIClient
    from managers.workflow_manager import WorkflowManager
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Please run this script from the root of the comfyui-mcp-server repository.")
    sys.exit(1)

# Minimal 1x1 PNG bytes for dummy/fallback image uploads
DUMMY_PNG_BYTES = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4'
    b'\x00\x00\x00\rIDATx\x9cc```\x00\x00\x00\x05\x00\x01\xa5\xf6E\xdd\x00\x00\x00\x00IEND\xaeB`\x82'
)

def download_image(base_url, filename, subfolder, folder_type, dest_path):
    """Download the generated image from ComfyUI and save it locally."""
    url = f"{base_url}/view?filename={filename}&subfolder={subfolder}&type={folder_type}"
    print(f"Downloading generated image from: {url}")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(response.content)
        print(f"[+] Saved generated image to: {dest_path}")
        return True
    except Exception as e:
        print(f"[X] Failed to download image: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Trigger and test ComfyUI workflows.")
    parser.add_argument(
        "-w", "--workflow",
        choices=["text-image", "image-image", "image_reference_and_text_to_image"],
        default="text-image",
        help="The workflow to execute (default: text-image)"
    )
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        default="A beautiful, vibrant digital art of a celestial phoenix rising from ashes, highly detailed, fantasy illustration",
        help="The prompt to inject into the workflow"
    )
    parser.add_argument(
        "-i", "--image",
        type=str,
        default=None,
        help="Path to a local input/reference image (required for image-image and reference workflows)"
    )
    parser.add_argument(
        "-u", "--url",
        type=str,
        default=os.getenv("COMFYUI_URL", "http://localhost:8188"),
        help="ComfyUI API URL (default: http://localhost:8188, or COMFYUI_URL env var if set)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="output_test.png",
        help="Filename to save the generated output image (default: output_test.png)"
    )
    parser.add_argument(
        "-a", "--aspect-ratio",
        type=str,
        default=None,
        help="Aspect ratio of the output image (e.g. '1:1 (Square)', '16:9 (Widescreen)', '9:16 (Portrait Widescreen)')"
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the final rendered workflow JSON and exit without submitting to ComfyUI"
    )
    args = parser.parse_args()

    # If print-only and we don't want to connect to ComfyUI, we can skip checking connection,
    # but let's check it unless print-only is enabled.
    if not args.print_only:
        print(f"[*] Connecting to ComfyUI at: {args.url}")
        client = ComfyUIClient(args.url)

        # Simple check if ComfyUI is up
        try:
            response = requests.get(f"{args.url}/object_info/CheckpointLoaderSimple", timeout=5)
            response.raise_for_status()
            print("[+] ComfyUI connection verified!")
        except Exception as e:
            print(f"[X] ComfyUI is not reachable at {args.url}. Please start ComfyUI first. Error: {e}")
            sys.exit(1)
    else:
        # Dummy client for print-only uploads if needed (won't be called)
        client = None

    # Initialize WorkflowManager
    workflows_dir = Path(__file__).parent / "workflows"
    print(f"[*] Loading workflows from: {workflows_dir}")
    workflow_manager = WorkflowManager(workflows_dir)

    workflow_id = args.workflow
    print(f"[*] Loading workflow: '{workflow_id}'")
    workflow = workflow_manager.load_workflow(workflow_id)
    if not workflow:
        print(f"[X] Failed to load workflow '{workflow_id}'")
        sys.exit(1)

    # 1. Apply prompt and aspect ratio overrides
    overrides = {"prompt": args.prompt}
    if args.aspect_ratio:
        overrides["aspect_ratio"] = args.aspect_ratio
    elif workflow_id == "text-image":
        overrides["aspect_ratio"] = "9:16 (Portrait Widescreen)"
        
    print(f"[*] Injecting overrides: {overrides}")
    try:
        # DefaultsManager is not required, pass None
        workflow = workflow_manager.apply_workflow_overrides(workflow, workflow_id, overrides, None)
        # Pop the override report if it's there
        workflow.pop("__override_report__", None)
    except Exception as e:
        print(f"[X] Failed to apply overrides: {e}")
        sys.exit(1)

    # 2. Handle image inputs if needed
    has_load_image = any(
        isinstance(node, dict) and node.get("class_type") == "LoadImage"
        for node in workflow.values()
    )

    if has_load_image:
        uploaded_filename = None
        if args.image:
            if not args.print_only:
                if not os.path.exists(args.image):
                    print(f"[X] Input image file not found: {args.image}")
                    sys.exit(1)
                print(f"[*] Uploading input image: {args.image}")
                try:
                    with open(args.image, "rb") as f:
                        image_bytes = f.read()
                    filename = os.path.basename(args.image)
                    upload_res = client.upload_image(image_bytes, filename)
                    uploaded_filename = upload_res.get("name")
                    print(f"[+] Uploaded successfully! Target filename in ComfyUI: {uploaded_filename}")
                except Exception as e:
                    print(f"[X] Failed to upload input image: {e}")
                    sys.exit(1)
            else:
                uploaded_filename = os.path.basename(args.image)
        else:
            # Check if workflow is image-image or reference and warn if no image provided
            if workflow_id in ["image-image", "image_reference_and_text_to_image"]:
                fallback_name = "image_flux2_input_image.png" if workflow_id == "image-image" else "input_reference_layout.png"
                if not args.print_only:
                    print(f"[!] Warning: Workflow '{workflow_id}' expects an input image, but none was provided via --image.")
                    print("[*] Uploading a dummy 1x1 image as fallback to prevent ComfyUI errors...")
                    try:
                        upload_res = client.upload_image(DUMMY_PNG_BYTES, fallback_name)
                        uploaded_filename = upload_res.get("name")
                        print(f"[+] Fallback dummy image uploaded as: {uploaded_filename}")
                    except Exception as e:
                        print(f"[X] Failed to upload fallback dummy image: {e}")
                        sys.exit(1)
                else:
                    uploaded_filename = fallback_name

        # Replace LoadImage filename in workflow if we have an uploaded filename
        if uploaded_filename:
            for node_id, node in workflow.items():
                if isinstance(node, dict) and node.get("class_type") == "LoadImage":
                    inputs = node.get("inputs", {})
                    if "image" in inputs:
                        print(f"[*] Updating LoadImage node '{node_id}' image input from {inputs['image']!r} to {uploaded_filename!r}")
                        inputs["image"] = uploaded_filename

    # Print-only check
    if args.print_only:
        import json
        print("\n=== Final Rendered Workflow JSON ===")
        print(json.dumps(workflow, indent=2))
        print("====================================")
        sys.exit(0)

    # 3. Submit workflow to ComfyUI
    print("[*] Submitting workflow to ComfyUI and waiting for completion...")
    try:
        # Determine output preferences
        preferred_output_keys = workflow_manager._guess_output_preferences(workflow)
        
        # We increase the max_attempts (which acts as timeout seconds) to 300 (5 mins) for heavy generations
        result = client.run_custom_workflow(workflow, preferred_output_keys=preferred_output_keys, max_attempts=300)
        
        if result.get("status") == "running":
            print(f"[!] Workflow is still running in background. Prompt ID: {result.get('prompt_id')}")
            sys.exit(0)
            
        print("[+] Generation completed successfully!")
        filename = result.get("filename")
        subfolder = result.get("subfolder")
        folder_type = result.get("folder_type")
        
        print(f"  Prompt ID: {result.get('prompt_id')}")
        print(f"  Output filename: {filename}")
        print(f"  Output subfolder: {subfolder}")
        print(f"  Output folder type: {folder_type}")
        
        # 4. Download output
        if filename:
            download_image(args.url, filename, subfolder, folder_type, args.output)
        else:
            print("[X] No output filename returned in results.")
            
    except Exception as e:
        print(f"[X] Failed to execute workflow: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
