from flask import Flask, send_from_directory, request, jsonify
import os
from flask_cors import CORS
import requests
import logging
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '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')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

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

def llm_chat(system_prompt, user_message):
    if not OPENAI_API_KEY:
        return None
    try:
        resp = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={'Authorization': 'Bearer ' + OPENAI_API_KEY, 'Content-Type': 'application/json'},
            json={
                'model': 'gpt-4o-mini',
                'messages': [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_message}],
                'max_tokens': 400,
                'temperature': 0.7
            },
            timeout=15
        )
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        logger.error('OpenAI error: ' + str(e))
        return None

def conversational_reply(query):
    system = (
        "You are AISENS, a friendly and knowledgeable AI assistant. "
        "You have access to real-time web search for factual questions. "
        "For casual conversation, greetings, and small talk, respond naturally and warmly. "
        "Keep replies concise (1-3 sentences). Do not use markdown formatting."
    )
    result = llm_chat(system, query)
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
    context_parts = []
    for r in results[:3]:
        context_parts.append('- ' + r.get('title', '') + ': ' + r.get('content', '')[:300])
    context_str = ' | '.join(context_parts)
    if raw_answer or context_parts:
        system = (
            "You are AISENS, a friendly AI assistant with real-time web search. "
            "Using the search results provided, write a clear, natural, conversational answer "
            "to the user's question. Be concise (2-4 sentences). Do not use bullet points or markdown. "
            "Do not say 'according to my search' — just answer directly and naturally."
        )
        user_msg = 'Question: ' + query + ' | Search answer: ' + raw_answer + ' | Top results: ' + context_str
        natural_answer = llm_chat(system, user_msg)
        if natural_answer:
            summary = natural_answer
        else:
            summary = raw_answer or (results[0].get('content', '')[:500] if results else 'No results found.')
    else:
        summary = "I couldn't find relevant information for that query. Could you rephrase it?"
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
            logger.info('Conversational reply (no search)')
            reply = conversational_reply(query)
            return jsonify({'type': 'result', 'data': {'summary': reply, 'sources': []}})
        logger.info('Web search')
        summary, sources = search_and_reply(query)
        return jsonify({'type': 'result', 'data': {'summary': summary, 'sources': sources}})
    except requests.exceptions.Timeout:
        return jsonify({'type': 'error', 'message': 'Search timed out. Please try again.'}), 504
    except requests.exceptions.HTTPError as e:
        return jsonify({'type': 'error', 'message': 'Search API error: ' + str(e)}), 502
    except Exception as e:
        logger.error('Error: ' + str(e))
        return jsonify({'type': 'error', 'message': 'Error: ' + str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logger.info('Starting server on port ' + str(port))
    app.run(host='0.0.0.0', port=port, debug=False)
