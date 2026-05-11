import os
import re
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime

app = Flask(__name__, static_folder='.')


def clean_text(text):
    """Remove markdown headings and clean up text for use in summaries."""
    # Remove markdown heading syntax
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_sentences(text, max_chars=300):
    """Extract clean sentences up to max_chars."""
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_dot = max(truncated.rfind('.'), truncated.rfind('!'))
    if last_dot > 80:
        return truncated[:last_dot + 1]
    return truncated.rstrip() + '...'


def web_search(query):
    """Search the web using DuckDuckGo (no API key required)."""
    try:
        from duckduckgo_search import DDGS
        results_list = []
        answer = ''
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        for r in results:
            results_list.append({
                'title': r.get('title', ''),
                'content': r.get('body', ''),
                'url': r.get('href', '')
            })
        # Build a simple answer from first result
        if results_list:
            answer = results_list[0].get('content', '')
        return answer.strip(), results_list
    except Exception as e:
        return None, []


def build_reply(answer, results):
    """
    Build a structured JSON-serialisable reply with:
      - summary: first result content (cleaned)
      - sources: list of {title, snippet, url}
    """
    summary = clean_text(answer) if answer and len(answer) > 15 else ''
    sources = []
    seen_titles = set()
    seen_urls = set()
    for res in results[:5]:
        title = (res.get('title') or '').strip()
        content = (res.get('content') or '').strip()
        url = (res.get('url') or '').strip()
        url_key = url.split('?')[0].rstrip('/')
        title_key = title.lower()[:60]
        if url_key in seen_urls or title_key in seen_titles:
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        snippet = extract_sentences(content, 250) if content else ''
        domain = ''
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace('www.', '')
        except Exception:
            pass
        sources.append({
            'title': title,
            'snippet': snippet,
            'url': url,
            'domain': domain
        })
    return {
        'summary': summary,
        'sources': sources
    }


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = (data.get('message') or '').strip()
    if not user_message:
        return jsonify({'type': 'error', 'message': 'Please send a message.'})
    answer, results = web_search(user_message)
    if answer is None:
        return jsonify({'type': 'error', 'message': 'Web search unavailable. DuckDuckGo search failed.'})
    reply = build_reply(answer, results)
    return jsonify({'type': 'result', 'data': reply})


@app.route('/debug')
def debug():
    query = request.args.get('q', 'news Spain')
    try:
        answer, results = web_search(query)
        return jsonify({'answer': answer, 'results': results})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'time': datetime.utcnow().isoformat()})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
