import os
from flask import Flask, request, jsonify, send_from_directory
import requests
from datetime import datetime

app = Flask(__name__, static_folder='.')

TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '')


def web_search(query):
    """Search the web using Tavily and return a rich answer."""
    if not TAVILY_API_KEY:
        return None, []
    try:
        r = requests.post(
            'https://api.tavily.com/search',
            json={
                'api_key': TAVILY_API_KEY,
                'query': query,
                'search_depth': 'advanced',
                'max_results': 5,
                'include_answer': True,
                'include_raw_content': False
            },
            timeout=20
        )
        data = r.json()
        answer = data.get('answer', '') or ''
        results = data.get('results', [])
        return answer.strip(), results
    except Exception as e:
        return None, []


def build_reply(answer, results):
    """Build a rich reply combining Tavily answer and top results."""
    sections = []

    # Always include the Tavily answer if meaningful
    if answer and len(answer) > 10:
        sections.append(answer)

    # Always include content from top results
    for res in results[:3]:
        title = res.get('title', '').strip()
        content = res.get('content', '').strip()
        url = res.get('url', '').strip()
        entry_parts = []
        if title:
            entry_parts.append(f'**{title}**')
        if content:
            snippet = content[:600]
            last_dot = snippet.rfind('.')
            if last_dot > 80:
                snippet = snippet[:last_dot + 1]
            entry_parts.append(snippet)
        if url:
            entry_parts.append(url)
        if entry_parts:
            sections.append('\n'.join(entry_parts))

    if not sections:
        # Last resort: show raw result titles
        if results:
            lines = []
            for res in results[:5]:
                t = res.get('title', '')
                u = res.get('url', '')
                if t or u:
                    lines.append(f'{t} - {u}' if t and u else t or u)
            if lines:
                return 'Here are the top results I found:\n\n' + '\n'.join(lines)
        return 'I searched the web but could not find relevant results. Please try rephrasing your question.'

    return '\n\n---\n\n'.join(sections)


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/debug', methods=['GET'])
def debug():
    """Debug endpoint to test Tavily raw response."""
    query = request.args.get('q', 'latest news Spain')
    if not TAVILY_API_KEY:
        return jsonify({'error': 'No TAVILY_API_KEY set'})
    try:
        r = requests.post(
            'https://api.tavily.com/search',
            json={
                'api_key': TAVILY_API_KEY,
                'query': query,
                'search_depth': 'basic',
                'max_results': 3,
                'include_answer': True
            },
            timeout=20
        )
        return jsonify(r.json())
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'reply': 'Please send a message.'})
    answer, results = web_search(user_message)
    if answer is None:
        return jsonify({'reply': 'Web search is not available. Please check TAVILY_API_KEY.'})
    reply = build_reply(answer, results)
    return jsonify({'reply': reply})


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'aisens-web', 'time': datetime.utcnow().isoformat()})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
