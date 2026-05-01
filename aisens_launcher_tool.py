from mcp.server.fastmcp import FastMCP
import logging
import requests
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('aisens_launcher')

AISENS_URL = os.environ.get('AISENS_URL', 'https://crane-slinging-revert.ngrok-free.dev/command')

mcp = FastMCP('AISENS Launcher')

def send_command(command_id: str) -> str:
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
        data = response.json()
        spoken = {
            "open_excel": "Opening Excel now.",
            "open_edge": "Opening Edge browser now.",
            "open_outlook_classic": "Opening classic Outlook now.",
            "open_copilot": "Opening Copilot now.",
            "open_comet": "Opening Comet now.",
        }.get(command_id, "Command sent.")
        if data.get("success"):
            logger.info(f'Launched: {command_id}')
            return spoken
        else:
            return f"Sorry, I could not open the app. {data.get('message', '')}"
    except requests.exceptions.ConnectionError:
        return "Sorry, I cannot reach the AISENS system right now. Make sure the launcher is running on your PC."
    except requests.exceptions.Timeout:
        return "Sorry, AISENS took too long to respond."
    except Exception as e:
        logger.error(f'Error: {e}')
        return f"Sorry, an unexpected error occurred: {e}"

@mcp.tool()
def open_excel() -> str:
    """Opens Microsoft Excel on the user laptop. Use when user says open Excel, launch Excel, abrir Excel."""
    return send_command("open_excel")

@mcp.tool()
def open_edge() -> str:
    """Opens Microsoft Edge browser on the user laptop. Use when user says open browser, open Edge, abrir navegador, open internet."""
    return send_command("open_edge")

@mcp.tool()
def open_outlook_classic() -> str:
    """Opens classic Outlook email client on the user laptop. Use when user says open Outlook, open email, abrir Outlook, abrir correo."""
    return send_command("open_outlook_classic")

@mcp.tool()
def open_copilot() -> str:
    """Opens Microsoft 365 Copilot on the user laptop. Use when user says open Copilot, launch Copilot, abrir Copilot."""
    return send_command("open_copilot")

@mcp.tool()
def open_comet() -> str:
    """Opens Perplexity Comet browser on the user laptop. Use when user says open Comet, open Perplexity, abrir Comet."""
    return send_command("open_comet")

if __name__ == '__main__':
    mcp.run(transport='stdio')
