from flask import Flask, send_from_directory, request, jsonify
import os
import re
import time
import base64
from flask_cors import CORS
import requests
import logging
from urllib.parse import urlparse
from openai import OpenAI
from datetime import datetime
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
# Only explicit greetings/small-talk are treated as conversational.
# Everything else (including short topic queries) goes to search.
CONVERSATIONAL_EXACT = {
    'hello', 'hi', 'hey', 'bye', 'goodbye', 'thanks', 'thank you',
    'good morning', 'good afternoon', 'good evening', 'good night',
    'how are you', 'how r you', "what's up", 'whats up',
    'who are you', 'what are you', 'what can you do',
    'introduce yourself', 'nice to meet you', 'see you',
    'are you ok', 'are you alive', 'are you real', 'are you human',
}

CONVERSATIONAL_STARTS = [
    'hello ', 'hi ', 'hey ', 'good morning', 'good afternoon',
    'good evening', 'good night', 'how are you', 'how r you',
    'nice to meet', 'thank you', 'thanks ',
]

def is_conversational(text):
    lower = text.lower().strip()
    # Exact match check
    if lower in CONVERSATIONAL_EXACT:
        return True
    # Starts-with check for greetings
    if any(lower.startswith(pat) for pat in CONVERSATIONAL_STARTS):
        return True
    # Default: treat as a search query
    return False

# --- DuckDuckGo HTML search ---
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

def normalize(text):
    return re.sub(r'\s+', ' ', text or '').strip()

def extract_sentences(text, max_chars=350):
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_dot = max(truncated.rfind('.'), truncated.rfind('!'))
    if last_dot > 80:
        return truncated[:last_dot + 1]
    return truncated.rstrip() + '...'

def search_ddg_html(query, max_results=5):
    try:
        session = requests.Session()
        r = session.post(
            'https://html.duckduckgo.com/html/',
            data={'q': query, 'b': '', 'kl': 'en-us'},
            headers=BROWSER_HEADERS,
            timeout=8,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')
        results = []
        for result in soup.select('.result')[:max_results]:
            title_el = result.select_one('.result__title')
            snippet_el = result.select_one('.result__snippet')
            url_el = result.select_one('.result__url')
            title = normalize(title_el.get_text(separator=' ')) if title_el else ''
            snippet = normalize(snippet_el.get_text(separator=' ')) if snippet_el else ''
            url = normalize(url_el.get_text(separator=' ')) if url_el else ''
            if title or snippet:
                results.append({'title': title, 'snippet': snippet, 'url': url})
        return results
    except Exception as e:
        logger.warning(f'DDG HTML search failed: {e}')
        return []

def ddg_search(query):
    cached = cache_get('ddg:' + query)
    if cached:
        logger.info(f'Cache hit: {query}')
        return cached
    results = search_ddg_html(query)
    if not results:
        logger.warning('DDG returned no results, falling back to OpenAI')
        return openai_search(query)
    combined = ' '.join(r['snippet'] for r in results if r['snippet'])
    summary = extract_sentences(combined, max_chars=350)
    if not summary:
        summary = results[0].get('title', 'I found some results but could not extract a summary.')
    sources = [{'url': r['url'], 'title': r['title']} for r in results if r['url']]
    result = (summary, sources)
    cache_set('ddg:' + query, result)
    return result

# --- Perplexity search (if key available) ---
def perplexity_chat(system, user_msg, use_search=False):
    if not PPLX_API_KEY:
        return None, []
    try:
        model = 'llama-3.1-sonar-small-128k-online' if use_search else 'llama-3.1-sonar-small-128k-chat'
        pplx_client = OpenAI(api_key=PPLX_API_KEY, base_url='https://api.perplexity.ai')
        response = pplx_client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user_msg},
            ],
            max_tokens=300,
            temperature=0.2,
        )
        answer = response.choices[0].message.content.strip()
        citations = getattr(response, 'citations', [])
        return answer, citations
    except Exception as e:
        logger.warning(f'Perplexity API error: {e}')
        return None, []

def perplexity_search(query):
    system = (
        'You are AISENS, a friendly AI assistant with real-time web search. '
        'Answer the user question directly and naturally in 2-4 sentences. '
        'Do not use bullet points or markdown. Be conversational and informative.'
    )
    answer, citations = perplexity_chat(system, query, use_search=True)
    if not answer:
        return ddg_search(query)
    sources = [{'url': c, 'title': urlparse(c).netloc} for c in (citations or [])]
    return answer, sources

# --- OpenAI fallback ---
def openai_search(query):
    try:
        system = (
            'You are AISENS, a helpful AI assistant. '
            'Answer the question directly in 2-3 sentences without bullet points or markdown.'
        )
        response = openai_client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': query},
            ],
            max_tokens=250,
            temperature=0.3,
        )
        answer = response.choices[0].message.content.strip()
        return answer, []
    except Exception as e:
        logger.error(f'OpenAI search failed: {e}')
        return 'I was unable to find an answer to that question right now. Please try again.', []

def search_and_reply(query):
    if PPLX_API_KEY:
        return perplexity_search(query)
    return ddg_search(query)

# --- Conversational reply ---
def conversational_reply(query):
    system = (
        'You are AISENS, a friendly AI assistant for Alexa. '
        'For greetings and small talk, respond naturally and warmly in 1-2 sentences. '
        'Do not use markdown or bullet points.'
    )
    answer, _ = perplexity_chat(system, query, use_search=False)
    if answer:
        return answer
    try:
        response = openai_client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': query},
            ],
            max_tokens=100,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return 'Hello! I am AISENS. Ask me anything and I will find the answer for you.'

# --- Routes ---
@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()})

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json(force=True)
    query = (data.get('message') or data.get('query') or '').strip()
    if not query:
        return jsonify({'type': 'error', 'message': 'No query provided'}), 400
    logger.info(f'Query received: {query}')
    try:
        if is_conversational(query):
            logger.info('Routing as conversational')
            reply = conversational_reply(query)
            return jsonify({'type': 'result', 'data': {'summary': reply, 'sources': []}})
        logger.info('Routing as search')
        summary, sources = search_and_reply(query)
        return jsonify({'type': 'result', 'data': {'summary': summary, 'sources': sources}})
    except Exception as e:
        logger.error(f'Chat error: {e}')
        return jsonify({'type': 'error', 'message': str(e)}), 500

@app.route('/snap')
def snap():
    try:
        resp = requests.get(CAMERA_URL, timeout=5)
        img_b64 = base64.b64encode(resp.content).decode('utf-8')
        return jsonify({'image': img_b64})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
