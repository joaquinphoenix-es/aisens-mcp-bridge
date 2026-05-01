import sys
import json
import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AISENS_URL = "https://crane-slinging-revert.ngrok-free.dev/command"

WHITELIST = {
    "open_excel",
    "open_edge",
    "open_outlook_classic",
    "open_copilot",
    "open_comet",
}

SPOKEN_RESPONSES = {
    "open_excel": "Opening Excel now.",
    "open_edge": "Opening Edge browser now.",
    "open_outlook_classic": "Opening classic Outlook now.",
    "open_copilot": "Opening Copilot now.",
    "open_comet": "Opening Comet now.",
}

TOOLS = [
    {
        "name": "open_excel",
        "description": "Opens Microsoft Excel on the user laptop. Use when user says open Excel, launch Excel, abrir Excel.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "open_edge",
        "description": "Opens Microsoft Edge browser on the user laptop. Use when user says open browser, open Edge, abrir navegador.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "open_outlook_classic",
        "description": "Opens classic Outlook email client on the user laptop. Use when user says open Outlook, abrir Outlook.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "open_copilot",
        "description": "Opens Microsoft 365 Copilot on the user laptop. Use when user says open Copilot, launch Copilot, abrir Copilot.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "open_comet",
        "description": "Opens Perplexity Comet browser on the user laptop. Use when user says open Comet, open Perplexity, abrir Comet.",
        "inputSchema": {"type": "object", "properties": {}, "required": []}
    },
]


def send_command(command_id: str) -> dict:
    try:
        response = requests.post(
            AISENS_URL,
            json={"command": command_id},
            headers={
                "Content-Type": "application/json",
                "ngrok-skip-browser-warning": "true"
            },
            timeout=10
        )
        try:
            return response.json()
        except Exception:
            return {"success": False, "message": f"Bad response: {response.status_code}",
                    "spoken_response": "Sorry, AISENS returned an unexpected response."}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": "AISENS listener not reachable",
                "spoken_response": "Sorry, I cannot reach the AISENS system right now."}
    except requests.exceptions.Timeout:
        return {"success": False, "message": "AISENS timeout",
                "spoken_response": "Sorry, AISENS took too long to respond."}
    except Exception as e:
        return {"success": False, "message": str(e),
                "spoken_response": "Sorry, an unexpected error occurred."}


def handle_request(req: dict) -> dict:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "aisens-launcher", "version": "1.0.0"}
            }
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS}
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        if tool_name not in WHITELIST:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Rejected: {tool_name} is not in whitelist."}],
                    "isError": True
                }
            }
        result = send_command(tool_name)
        spoken = result.get("spoken_response", SPOKEN_RESPONSES.get(tool_name, "Command sent."))
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": spoken}],
                "isError": not result.get("success", False)
            }
        }

    elif method == "notifications/initialized":
        return None

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }


def main():
    logger.info("AISENS Launcher MCP tool starting...")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            response = handle_request(req)
            if response is not None:
                print(json.dumps(response), flush=True)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
