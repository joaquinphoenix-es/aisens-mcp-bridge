"""
start.py — Unified entrypoint for Railway.
Launches both:
  1. mcp_pipe.py  -> connects to xiaozhi wss:// endpoint (live data for the voice agent)
  2. server.py    -> Flask chat API (text interface)

Both run concurrently. If mcp_pipe crashes it auto-retries (built into mcp_pipe).
Flask is the foreground process; mcp_pipe runs as a daemon thread.
"""
import os
import sys
import threading
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger('START')

def run_mcp_pipe():
    """Run mcp_pipe.py in a subprocess (it has its own retry logic)."""
    mcp_endpoint = os.environ.get('MCP_ENDPOINT')
    if not mcp_endpoint:
        logger.warning("MCP_ENDPOINT not set — skipping mcp_pipe (xiaozhi MCP bridge won't start)")
        return

    logger.info(f"Starting MCP pipe -> {mcp_endpoint}")
    while True:
        try:
            result = subprocess.run(
                [sys.executable, 'mcp_pipe.py'],
                env=os.environ.copy()
            )
            logger.warning(f"mcp_pipe.py exited with code {result.returncode}, restarting in 5s...")
        except Exception as e:
            logger.error(f"mcp_pipe.py crashed: {e}, restarting in 5s...")
        import time
        time.sleep(5)

# Start mcp_pipe in a background daemon thread
mcp_thread = threading.Thread(target=run_mcp_pipe, daemon=True, name='mcp-pipe')
mcp_thread.start()

# Now start Flask (this blocks)
logger.info("Starting Flask chat server...")
from server import app
port = int(os.environ.get('PORT', 8080))
logger.info(f"Flask listening on port {port}")
app.run(host='0.0.0.0', port=port, debug=False)
