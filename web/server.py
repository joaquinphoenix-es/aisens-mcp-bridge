import os
from flask import Flask, request, jsonify, send_from_directory
import requests
from datetime import datetime

app = Flask(__name__, static_folder='.')

TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '')


def web_search(query):
    """Search the web using Tavily and return a rich answer."""
    if not TAVILY_API_KEY:
        return None, None
    try:
        r = requests.post(
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
        data = r.json()
        answer = data.get('answer', '')
        results = data.get('results', [])
        return answer, results
    except Exception as e:
        return None, None


def build_reply(user_message, answer, results):
    """Build a clean, readable reply from Tavily results."""
    if answer and len(answer) > 30:
        reply = answer
        if results:
            sources = []
            for r in results[:3]:
                title = r.get('title', '')
                url = r.get('url', '')
                if title and url:
                    sources.append(f"- {title}")
            if sources:
                reply += "\n\nSources:\n" + "\n".join(sources)
        return reply

    if results:
        parts = []
        for r in results[:3]:
            title = r.get('title', '')
            content = r.get('content', '')[:300]
            if title and content:
                parts.append(f"{title}:\n{content}")
        if parts:
            return "Here is what I found:\n\n" + "\n\n".join(parts)

    return "I searched the web but could not find a clear answer to your question. Please try rephrasing."


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'reply': 'Please send a message.'})

    # Search the web
    answer, results = web_search(user_message)

    if answer is None and results is None:
        return jsonify({'reply': 'AISENS web search is not configured. Please set TAVILY_API_KEY.'})

    reply = build_reply(user_message, answer, results)
    return jsonify({'reply': reply})


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'aisens-web', 'time': datetime.utcnow().isoformat()})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
