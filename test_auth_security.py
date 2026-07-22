"""Authentication & Security tests for ComfyUI MCP Server"""

import os
import sys
import time
import subprocess
import requests

SERVER_PORT = 9099
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}/mcp"
TEST_API_KEY = "super-secret-mcp-test-key"

def run_tests():
    print(f"Starting test server on port {SERVER_PORT} with MCP_API_KEY={TEST_API_KEY}...")
    env = os.environ.copy()
    env["MCP_API_KEY"] = TEST_API_KEY
    env["MCP_PORT"] = str(SERVER_PORT)
    env["COMFY_SKIP_HEALTHCHECK"] = "1"

    # Launch server process
    proc = subprocess.Popen(
        [sys.executable, "server.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(__file__)
    )

    # Give server time to initialize and check if running
    for _ in range(30):
        if proc.poll() is not None:
            stdout, stderr = proc.communicate()
            print("Server process exited prematurely!")
            print("STDOUT:\n", stdout.decode())
            print("STDERR:\n", stderr.decode())
            sys.exit(1)
        try:
            r = requests.get(f"http://127.0.0.1:{SERVER_PORT}/mcp", timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    try:
        print("\n--- Test 1: Unauthenticated request (No Authorization header) ---")
        res1 = requests.post(SERVER_URL, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        print(f"Status Code: {res1.status_code}")
        print(f"Response: {res1.text}")
        assert res1.status_code == 401, f"Expected 401, got {res1.status_code}"
        print("✓ Test 1 Passed: Unauthenticated request returned 401 Unauthorized")

        print("\n--- Test 2: Invalid API Key ---")
        headers_invalid = {"Authorization": "Bearer wrong-key-123"}
        res2 = requests.post(SERVER_URL, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}, headers=headers_invalid)
        print(f"Status Code: {res2.status_code}")
        print(f"Response: {res2.text}")
        assert res2.status_code == 403, f"Expected 403, got {res2.status_code}"
        print("✓ Test 2 Passed: Invalid API Key returned 403 Forbidden")

        print("\n--- Test 3: Valid API Key ---")
        headers_valid = {
            "Authorization": f"Bearer {TEST_API_KEY}",
            "Accept": "application/json, text/event-stream"
        }
        res3 = requests.post(SERVER_URL, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}, headers=headers_valid)
        print(f"Status Code: {res3.status_code}")
        print(f"Response: {res3.text[:200] if len(res3.text) > 200 else res3.text}")
        assert res3.status_code != 401 and res3.status_code != 403, f"Expected authorized response, got {res3.status_code}"
        print("✓ Test 3 Passed: Valid API Key accepted (Authentication passed)")

        print("\n--- Test 4: Public Static /assets Endpoint ---")
        res4 = requests.get(f"http://127.0.0.1:{SERVER_PORT}/assets/nonexistent_file.png")
        print(f"Status Code: {res4.status_code}")
        # Public asset endpoint should bypass bearer auth (returns 404 for missing file instead of 401/403)
        assert res4.status_code == 404, f"Expected 404 for missing static file, got {res4.status_code}"
        print("✓ Test 4 Passed: Static /assets endpoint bypasses API key check for public asset viewing")

        print("\nAll authentication & security tests passed successfully!")

    finally:
        proc.terminate()
        proc.wait(timeout=5)

if __name__ == "__main__":
    run_tests()
