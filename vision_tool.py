import os
import base64
import logging
import requests
from openai import OpenAI
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('vision_tool')

CAMERA_URL = os.environ.get('CAMERA_URL', 'http://192.168.1.153/snap.jpg')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

mcp = FastMCP('AISENS Vision')


@mcp.tool()
def analyze_camera() -> str:
    """Capture an image from the AISENS camera and analyze it.
    Returns who is present, their emotional state, and a scene description.
    Use this when the user asks what you see, who is there, or how someone looks."""
    try:
        # Fetch snapshot from ESP32-CAM via ngrok tunnel
        logger.info(f'Fetching camera snapshot from {CAMERA_URL}')
        response = requests.get(CAMERA_URL, timeout=8)
        response.raise_for_status()

        # Encode image to base64
        image_b64 = base64.b64encode(response.content).decode('utf-8')
        logger.info('Snapshot captured, sending to vision API')

        # Send to GPT-4o Vision
        vision_response = client.chat.completions.create(
            model='gpt-4o',
            messages=[
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image_url',
                            'image_url': {
                                'url': f'data:image/jpeg;base64,{image_b64}',
                                'detail': 'low'
                            }
                        },
                        {
                            'type': 'text',
                            'text': (
                                'Analyze this image carefully. '
                                'Describe: 1) Who is present (physical description). '
                                '2) Their emotional state (happy, sad, tired, stressed, neutral, excited, etc). '
                                '3) What they appear to be doing. '
                                '4) The environment/scene briefly. '
                                'Be concise and natural, as if you are describing it to a friend. '
                                'If no person is visible, just describe the scene.'
                            )
                        }
                    ]
                }
            ],
            max_tokens=300
        )

        result = vision_response.choices[0].message.content
        logger.info(f'Vision analysis complete: {result[:100]}')
        return result

    except requests.exceptions.Timeout:
        return 'Camera is not responding. The ESP32-CAM may be offline or unreachable.'
    except requests.exceptions.ConnectionError:
        return 'Cannot connect to camera. Please check if the camera is powered and the ngrok tunnel is active.'
    except Exception as e:
        logger.error(f'Vision tool error: {e}')
        return f'Vision analysis failed: {str(e)}'


@mcp.tool()
def get_camera_snapshot_url() -> str:
    """Returns the live camera stream URL so the user can view it directly in a browser.
    Use this when the user wants to see the camera feed themselves."""
    stream_url = CAMERA_URL.replace('/snap.jpg', ':81/stream').replace('/snap.jpg', '')
    base_url = CAMERA_URL.replace('/snap.jpg', '')
    return (
        f'Camera snapshot: {CAMERA_URL}\n'
        f'Live stream: {base_url.replace("80", "81")}/stream\n'
        f'Open the stream URL in any browser to see the live feed.'
    )


if __name__ == '__main__':
    mcp.run(transport='stdio')
