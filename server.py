from flask import Flask, send_from_directory, request, jsonify
import os
import time
import base64
from flask_cors import CORS
import requests
import logging
from urllib.parse import urlparse
from openai import OpenAI
from datetime import datetime

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

# --- Simple in-memory cache with TTL ---
_cache = {}
CACHE_TTL = 300  # 5 minutes

def cache_get(key):
    entry = _cache.get(key)
    if entry and (time.time() - entry['ts']) < CACHE_TTL:
        return entry['value']
    return None

def cache_set(key, value):
    _cache[key] = {'value': value, 'ts': time.time()}

# --- Conversational pattern detection ---
CONVERSATIONAL_PATTERNS = [
    'hello', 'hi ', 'hey ', 'good morning', 'good afternoon', 'good evening',
    'good night', 'how are you', 'how r you', "what's up", 'whats up',
    'who are you', 'what are you', 'what can you do', 'introduce yourself',
    'your name', 'nice to meet', 'thank you', 'thanks', 'bye', 'goodbye',
    'see you', 'are you ok', 'are you alive', 'are you real', 'are you human',
    'do you understand', 'can you help', 'help me',
]

# Keywords that always force a search even if short
SEARCH_KEYWORDS = [
    'price', 'news', 'stock', 'weather', 'score', 'who won', 'latest',
    'what is', 'what are', 'what was', 'what will', 'how does', 'how do',
    'how much', 'how many', 'why is', 'why are', 'when is', 'when did',
    'where is', 'where are', 'who is', 'who was', 'define', 'explain',
    'tell me about', 'search for', 'look up', 'find out',
]

def is_conversational(text):
    lower = text.lower().strip()
    # Always search if a search keyword is present
    if any(kw in lower for kw in SEARCH_KEYWORDS):
        return False
    # Short queries without search keywords may be conversational
    if len(lower.split()) <= 3:
        return True
    return any(lower.startswith(pat) or (' ' + pat) in lower for pat in CONVERSATIONAL_PATTERNS)

# --- OpenAI-based search/answer (primary fallback) ---
def openai_search(query):
    if not OPENAI_API_KEY:
        return "I'm sorry, I couldn't find an answer right now.", []
    cached = cache_get('openai:' + query)
    if cached:
        logger.info('Cache hit: ' + query)
        return cached
    try:
        system = (
            "You are AISENS, a helpful AI voice assistant for Alexa. "
            "Answer the user's question directly, accurately, and conversationally in 2-4 sentences. "
            "Do not use bullet points, markdown, or special characters. "
            "Be concise — your answer will be spoken aloud. "
            "If you are unsure about recent events, say so and give the best answer you can."
        )
        response = openai_client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': query}
            ],
            max_tokens=300,
            temperature=0.5
        )
        answer = response.choices[0].message.content.strip()
        result = (answer, [])
        cache_set('openai:' + query, result)
        return result
    except Exception as e:
        logger.error('OpenAI error: ' + str(e))
        return "I'm sorry, I couldn't find an answer right now.", []

# --- Perplexity ---
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
                'return_citations': use_search
            },
            timeout=20
        )
        resp.raise_for_status()
        data = resp.json()
        content = data['choices'][0]['message']['content']
        citations = data.get('citations', [])
        return content, citations
    except Exception as e:
        logger.error('Perplexity error: ' + str(e))
        return None, []

def perplexity_search(query):
    system = (
        "You are AISENS, a friendly AI assistant with real-time web search. "
        "Answer the user's question directly and naturally in 2-4 sentences. "
        "Do not use bullet points or markdown. Be conversational and informative."
    )
    answer, citations = perplexity_chat(system, query, use_search=True)
    if not answer:
        return openai_search(query)
    sources = []
    for url in citations[:5]:
        try:
            domain = urlparse(url).netloc
        except Exception:
            domain = ''
        sources.append({'title': domain, 'url': url, 'snippet': '', 'domain': domain})
    return answer, sources

# --- Tavily ---
def tavily_search(query):
    if not TAVILY_API_KEY:
        return openai_search(query)
    cached = cache_get('tavily:' + query)
    if cached:
        logger.info('Cache hit: ' + query)
        return cached
    try:
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
        summary = raw_answer or (results[0].get('content', '')[:500] if results else None)
        if not summary:
            return openai_search(query)
        sources = []
        for r in results:
            url = r.get('url', '')
            domain = ''
            if url:
                try:
                    domain = urlparse(url).netloc
                except Exception:
                    pass
            sources.append({
                'title': r.get('title', 'Untitled'),
                'url': url,
                'snippet': r.get('content', '')[:300],
                'domain': domain
            })
        result = (summary, sources)
        cache_set('tavily:' + query, result)
        return result
    except Exception as e:
        logger.error('Tavily error: ' + str(e))
        return openai_search(query)

# --- Conversational reply ---
def conversational_reply(query):
    system = (
        "You are AISENS, a friendly AI assistant for Alexa. "
        "For greetings and small talk, respond naturally and warmly in 1-2 sentences. "
        "Do not use markdown or bullet points."
    )
    answer, _ = perplexity_chat(system, query, use_search=False)
    if answer:
        return answer
    # OpenAI fallback for conversational
    try:
        response = openai_client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': query}
            ],
            max_tokens=80,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Hello! I'm AISENS. Ask me anything and I'll find the answer for you."

# --- Main search dispatcher ---
def search_and_reply(query):
    if PPLX_API_KEY:
        return perplexity_search(query)
    return tavily_search(query)

# --- Routes ---
@app.route('/')
def index():
    return send_from_directory('web', 'index.html')

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
    except Exception as e:
        logger.error('Chat error: ' + str(e))
        return jsonify({'type': 'error', 'message': 'Internal server error'}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'aisens-mcp-bridge', 'time': datetime.utcnow().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
