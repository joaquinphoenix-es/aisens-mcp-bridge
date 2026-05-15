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
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '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')
SYNTHESIS_MODEL = os.environ.get('SYNTHESIS_MODEL', 'gpt-4o')

openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

app = Flask(__name__, static_folder='web', static_url_path='')
CORS(app)

_cache = {}
CACHE_TTL = 300

def cache_get(key):
    entry = _cache.get(key)
    if entry and (time.time() - entry['ts']) < CACHE_TTL:
        return entry['value']
    return None

def cache_set(key, value):
    _cache[key] = {'value': value, 'ts': time.time()}

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

INSTANT_REPLIES = {
    'hello': 'Hello! I am AISENS. What would you like to know?',
    'hi': 'Hi there! I am AISENS. Ask me anything!',
    'hey': 'Hey! I am AISENS. What can I help you with?',
    'bye': 'Goodbye! Have a great day!',
    'goodbye': 'Goodbye! Have a great day!',
    'thanks': 'You are welcome!',
    'thank you': 'You are welcome!',
    'how are you': 'I am doing great, thank you for asking! What can I help you find?',
    'good morning': 'Good morning! What would you like to know today?',
    'good afternoon': 'Good afternoon! How can I help you?',
    'good evening': 'Good evening! What can I find for you?',
    'who are you': 'I am AISENS, your AI-powered search assistant. Ask me anything!',
    'what are you': 'I am AISENS, an AI assistant that can search the web and answer your questions.',
    'what can you do': 'I can search the web and answer your questions. Just ask me anything!',
    "what's up": 'All good! What would you like to search for?',
    'whats up': 'All good! What would you like to search for?',
}

def is_conversational(text):
    lower = text.lower().strip()
    if lower in CONVERSATIONAL_EXACT:
        return True
    if any(lower.startswith(pat) for pat in CONVERSATIONAL_STARTS):
        return True
    return False

def clean_for_speech(text):
    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

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

def extract_sentences(text, max_chars=600):
    text = clean_for_speech(text)
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_dot = max(truncated.rfind('.'), truncated.rfind('!'))
    if last_dot > 80:
        return truncated[:last_dot + 1]
    return truncated.rstrip() + '...'

# --- Tavily search (PRIMARY - parity with XiaoZhi chatbot) ---
def tavily_search_api(query, max_results=8):
    if not TAVILY_API_KEY:
        return None
    try:
        r = requests.post(
            'https://api.tavily.com/search',
            json={
                'api_key': TAVILY_API_KEY,
                'query': query,
                'search_depth': 'advanced',
                'include_answer': True,
                'include_raw_content': False,
                'max_results': max_results,
            },
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f'Tavily API error: {e}')
        return None

def synthesize_answer(query, context_text):
    if not context_text:
        return ''
    try:
        system = (
            "You are AISENS, a knowledgeable research assistant. "
            "Using the provided context, write a comprehensive, detailed answer to the user's question. "
            "Include background, key actors, current developments, and relevant nuance. "
            "Aim for 8 to 12 sentences. Write in plain spoken British English. "
            "Do not use markdown, bullet points, headings, or citation numbers. "
            "If the context is insufficient, still answer using general knowledge and say what is uncertain."
        )
        user_msg = f"Question: {query}\n\nContext:\n{context_text[:8000]}"
        response = openai_client.chat.completions.create(
            model=SYNTHESIS_MODEL,
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user_msg},
            ],
            max_tokens=900,
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f'OpenAI synthesis failed: {e}')
        return extract_sentences(context_text, max_chars=1000)

def tavily_reply(query):
    cached = cache_get('tavily:' + query)
    if cached:
        logger.info(f'Tavily cache hit: {query}')
        return cached
    data = tavily_search_api(query)
    if not data:
        return None
    results = data.get('results', []) or []
    tavily_answer = (data.get('answer') or '').strip()
    # Always expand via LLM (parity with XiaoZhi's GPT-5 post-processing)
    snippets = '\n\n'.join(
        f"Source: {r.get('title','')}\n{r.get('content','')}"
        for r in results if r.get('content')
    )
    context = ''
    if tavily_answer:
        context += f"Tavily summary: {tavily_answer}\n\n"
    context += f"Detailed sources:\n{snippets}"
    summary = synthesize_answer(query, context)
    if not summary:
        summary = tavily_answer or (results[0].get('content', '') if results else '')
    summary = clean_for_speech(summary)
    if not summary:
        return None
    sources = [{'url': r.get('url', ''), 'title': r.get('title', '')} for r in results if r.get('url')]
    result = (summary, sources)
    cache_set('tavily:' + query, result)
    return result

# --- DuckDuckGo HTML fallback ---
def search_ddg_html(query, max_results=5):
    try:
        session = requests.Session()
        r = session.post(
            'https://html.duckduckgo.com/html/',
            data={'q': query, 'b': '', 'kl': 'en-us'},
            headers=BROWSER_HEADERS, timeout=8,
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
        return cached
    results = search_ddg_html(query)
    if not results:
        return openai_search(query)
    snippets = ' '.join(r['snippet'] for r in results if r['snippet'])
    summary = synthesize_answer(query, snippets) if snippets else ''
    if not summary:
        summary = results[0].get('title', 'I found some results but could not extract a summary.')
    sources = [{'url': r['url'], 'title': r['title']} for r in results if r['url']]
    result = (summary, sources)
    cache_set('ddg:' + query, result)
    return result

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
            max_tokens=600,
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
        'Answer the user question thoroughly in 4 to 6 sentences. '
        'Do not use bullet points or markdown. Be conversational and informative.'
    )
    answer, citations = perplexity_chat(system, query, use_search=True)
    if not answer:
        return None
    sources = [{'url': c, 'title': urlparse(c).netloc} for c in (citations or [])]
    return answer, sources

def openai_search(query):
    try:
        system = (
            'You are AISENS, a helpful AI assistant. '
            'Answer the question thoroughly in 4 to 6 sentences without bullet points or markdown.'
        )
        response = openai_client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': query},
            ],
            max_tokens=500,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip(), []
    except Exception as e:
        logger.error(f'OpenAI search failed: {e}')
        return 'I was unable to find an answer to that question right now. Please try again.', []

def search_and_reply(query):
    tav = tavily_reply(query)
    if tav and tav[0]:
        return tav
    if PPLX_API_KEY:
        pplx = perplexity_search(query)
        if pplx and pplx[0]:
            return pplx
    return ddg_search(query)

def conversational_reply(query):
    lower = query.lower().strip()
    if lower in INSTANT_REPLIES:
        return INSTANT_REPLIES[lower]
    system = (
        'You are AISENS, a friendly AI assistant. '
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
        return 'Hello! I am AISENS. What would you like to know?'

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
            reply = conversational_reply(query)
            return jsonify({'type': 'result', 'data': {'summary': reply, 'sources': []}})
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
