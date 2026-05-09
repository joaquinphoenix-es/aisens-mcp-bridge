from flask import Flask, send_from_directory, request, jsonify
import os
import base64
from flask_cors import CORS
import requests
import logging
from urllib.parse import urlparse
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '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')
PPLX_API_KEY = os.environ.get('PPLX_API_KEY', '')
CAMERA_URL = os.environ.get('CAMERA_URL', 'http://192.168.1.153/snap.jpg')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')

openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

app = Flask(__name__, static_folder='web', static_url_path='')
CORS(app)

CONVERSATIONAL_PATTERNS = [
    'hello', 'hi ', 'hey ', 'good morning', 'good afternoon', 'good evening',
    'good night', 'how are you', 'how r you', "what's up", 'whats up',
    'who are you', 'what are you', 'what can you do', 'introduce yourself',
    'your name', 'nice to meet', 'thank you', 'thanks', 'bye', 'goodbye',
    'see you', 'are you ok', 'are you alive', 'are you real', 'are you human',
    'do you understand', 'can you help', 'help me',
]

def is_conversational(text):
    lower = text.lower().strip()
    if len(lower.split()) <= 3 and not any(kw in lower for kw in ['price', 'news', 'stock', 'weather', 'score', 'who won', 'latest']):
        return True
    return any(lower.startswith(pat) or (' ' + pat) in lower for pat in CONVERSATIONAL_PATTERNS)

def perplexity_chat(system_prompt, user_message, use_search=False):
    if not PPLX_API_KEY:
        return None, []
    model = 'sonar'
    try:
        resp = requests.post(
            'https://api.perplexity.ai/chat/completions',
            headers={
                'Authorization': 'Bearer ' + PPLX_API_KEY,
                'Content-Type': 'application/json'
            },
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_message}
                ],
                'max_tokens': 400,
                'temperature': 0.7
            },
            timeout=20
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data['choices'][0]['message']['content'].strip()
        citations = data.get('citations', [])
        return answer, citations
    except Exception as e:
        logger.error('Perplexity error: ' + str(e))
        return None, []

def conversational_reply(query):
    system = (
        "You are AISENS, a friendly and knowledgeable AI assistant with real-time web search. "
        "For casual conversation, greetings and small talk, respond naturally and warmly. "
        "Keep replies concise (1-3 sentences). Do not use markdown formatting."
    )
    result, _ = perplexity_chat(system, query, use_search=False)
    if result:
        return result
    lower = query.lower()
    if any(w in lower for w in ['hello', 'hi ', 'hey ']):
        return "Hello! I'm AISENS, your AI assistant with live web search. What would you like to know today?"
    if 'how are you' in lower:
        return "I'm doing great and ready to help! Ask me anything — news, prices, weather, sports, or any topic you're curious about."
    if any(w in lower for w in ['who are you', 'what are you', 'your name']):
        return "I'm AISENS — an AI assistant with real-time internet access. I can search the web for current news, prices, weather, and much more."
    if any(w in lower for w in ['thank', 'thanks']):
        return "You're welcome! Let me know if there's anything else I can help with."
    if any(w in lower for w in ['bye', 'goodbye', 'see you']):
        return "Goodbye! Feel free to come back anytime you need information."
    return "I'm here to help! Ask me about current news, stock prices, weather, sports results, or anything you want to know."

def search_and_reply(query):
    if PPLX_API_KEY:
        return perplexity_search(query)
    return tavily_search(query)

def perplexity_search(query):
    system = (
        "You are AISENS, a friendly AI assistant with real-time web search. "
        "Answer the user's question directly and naturally in 2-4 sentences. "
        "Do not use bullet points or markdown. Be conversational and informative."
    )
    answer, citations = perplexity_chat(system, query, use_search=True)
    if not answer:
        return tavily_search(query)
    sources = []
    for url in citations[:5]:
        try:
            domain = urlparse(url).netloc
        except Exception:
            domain = ''
        sources.append({'title': domain, 'url': url, 'snippet': '', 'domain': domain})
    return answer, sources

def tavily_search(query):
    resp = requests.post(
        'https://api.tavily.com/search',
        json={
            'api_key': TAVILY_API_KEY,
            'query': query,
            'search_depth': 'basic',
            'max_results': 5,
            'include_answer': True
        },
        timeout=15
    )
    resp.raise_for_status()
    tavily_data = resp.json()
    raw_answer = tavily_data.get('answer', '')
    results = tavily_data.get('results', [])
    summary = raw_answer or (results[0].get('content', '')[:500] if results else "I couldn't find relevant information for that query.")
    sources = []
    for r in results:
        url = r.get('url', '')
        domain = ''
        if url:
            try:
                domain = urlparse(url).netloc
            except Exception:
                pass
        sources.append({'title': r.get('title', 'Untitled'), 'url': url, 'snippet': r.get('content', '')[:300], 'domain': domain})
    return summary, sources

@app.route('/')
def serve_index():
    return send_from_directory('web', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'aisens-mcp-bridge'})

@app.route('/vision', methods=['GET', 'POST'])
def vision():
    try:
        if request.method == 'POST':
            data = request.get_json(force=True) or {}
            prompt = data.get('prompt', 'Describe what you see. If there is a person, describe their appearance and emotional state.')
            cam_url = data.get('camera_url', CAMERA_URL)
        else:
            prompt = request.args.get('prompt', 'Describe what you see. If there is a person, describe their appearance and emotional state.')
            cam_url = request.args.get('camera_url', CAMERA_URL)

        if not OPENAI_API_KEY:
            return jsonify({'type': 'error', 'message': 'OPENAI_API_KEY not configured'}), 500

        logger.info('Fetching camera snapshot from: ' + cam_url)
        cam_resp = requests.get(cam_url, timeout=10)
        cam_resp.raise_for_status()
        image_b64 = base64.b64encode(cam_resp.content).decode('utf-8')
        content_type = cam_resp.headers.get('Content-Type', 'image/jpeg')

        logger.info('Sending image to GPT-4o Vision')
        completion = openai_client.chat.completions.create(
            model='gpt-4o',
            messages=[
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': prompt},
                        {'type': 'image_url', 'image_url': {'url': f'data:{content_type};base64,{image_b64}'}}
                    ]
                }
            ],
            max_tokens=500
        )
        analysis = completion.choices[0].message.content.strip()
        logger.info('Vision analysis complete')
        return jsonify({'type': 'result', 'data': {'analysis': analysis, 'camera_url': cam_url}})

    except requests.exceptions.Timeout:
        return jsonify({'type': 'error', 'message': 'Camera or API timed out'}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({'type': 'error', 'message': 'Cannot reach camera at ' + cam_url}), 502
    except Exception as e:
        logger.error('Vision error: ' + str(e))
        return jsonify({'type': 'error', 'message': 'Vision error: ' + str(e)}), 500

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({'type': 'error', 'message': 'Invalid JSON body'}), 400
        query = data.get('message', '').strip()
        if not query:
            return jsonify({'type': 'error', 'message': 'No message provided'}), 400
        logger.info('Query: ' + query)
        if is_conversational(query):
            logger.info('Conversational reply')
            reply = conversational_reply(query)
            return jsonify({'type': 'result', 'data': {'summary': reply, 'sources': []}})
        logger.info('Search query')
        summary, sources = search_and_reply(query)
        return jsonify({'type': 'result', 'data': {'summary': summary, 'sources': sources}})
    except requests.exceptions.Timeout:
        return jsonify({'type': 'error', 'message': 'Search timed out. Please try again.'}), 504
    except requests.exceptions.HTTPError as e:
        return jsonify({'type': 'error', 'message': 'Search API error: ' + str(e)}), 502
    except Exception as e:
        logger.error('Error: ' + str(e))
        return jsonify({'type': 'error', 'message': 'Error: ' + str(e)}), 500


@app.route('/snapshot')
def snapshot():
    try:
        headers = {'ngrok-skip-browser-warning': 'true'}
        cam_resp = requests.get(CAMERA_URL, timeout=10, headers=headers)
        cam_resp.raise_for_status()
        content_type = cam_resp.headers.get('Content-Type', 'image/jpeg')
        return cam_resp.content, 200, {'Content-Type': content_type, 'Cache-Control': 'no-store'}
    except Exception as e:
        logger.error('Snapshot error: ' + str(e))
        return jsonify({'error': str(e)}), 502

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logger.info('Starting server on port ' + str(port))
    app.run(host='0.0.0.0', port=port, debug=False)
