import os
import base64
import logging
import requests
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('vision_tool')

CAMERA_URL = os.environ.get('CAMERA_URL', 'http://192.168.1.153/snapshot.jpg')

mcp = FastMCP('AISENS Vision')


@mcp.tool()
def analyze_camera() -> str:
    """Capture a live image from the AISENS ESP32-CAM and return it as a
    base64 data URL so the AI model can analyze it directly.
    Use this tool when the user asks what you see, who is in the room,
    how many people are there, what someone looks like, or their emotion.
    """
    try:
        logger.info('Fetching camera snapshot from: ' + CAMERA_URL)
        headers = {'ngrok-skip-browser-warning': 'true'}
        response = requests.get(CAMERA_URL, timeout=10, headers=headers)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', 'image/jpeg')
        image_b64 = base64.b64encode(response.content).decode('utf-8')
        data_url = f'data:{content_type};base64,{image_b64}'
        logger.info('Camera snapshot captured successfully')
        return (
            f'I have captured a live image from the AISENS camera. '
            f'Here is the image as a data URL for you to analyze: {data_url}\n\n'
            f'Please describe in detail: who is in the room, their appearance, '
            f'estimated age, gender, clothing, and emotional state.'
        )
    except requests.exceptions.ConnectionError:
        return 'Error: Cannot reach the camera. The ngrok tunnel may be offline or the camera is off.'
    except requests.exceptions.Timeout:
        return 'Error: Camera timed out. The device may be unresponsive.'
    except Exception as e:
        logger.error('Vision error: ' + str(e))
        return f'Error capturing camera image: {str(e)}'


if __name__ == '__main__':
    mcp.run()
