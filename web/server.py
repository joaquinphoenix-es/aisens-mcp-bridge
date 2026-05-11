import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime

app = Flask(__name__, static_folder='.')

# Browser-like headers to bypass datacenter IP blocks
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}


def clean_text(text):
    """Remove markdown headings and clean up text for use in summaries."""
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
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


def search_ddg_html(query, max_results=5):
    """Scrape DuckDuckGo HTML search results directly (works from cloud IPs)."""
    try:
        session = requests.Session()
        # First request to get a vqd token
        params = {'q': query, 'b': '', 'kl': 'en-us'}
        r = session.post(
            'https://html.duckduckgo.com/html/',
            data=params,
            headers=BROWSER_HEADERS,
            timeout=15
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        for result in soup.select('.result__body')[:max_results]:
            title_el = result.select_one('.result__title')
            snippet_el = result.select_one('.result__snippet')
            url_el = result.select_one('.result__url')
            title = title_el.get_text(strip=True) if title_el else ''
            snippet = snippet_el.get_text(strip=True) if snippet_el else ''
            url = ''
            if url_el:
                url = url_el.get_text(strip=True)
                if not url.startswith('http'):
                    url = 'https://' + url
            if title or snippet:
                results.append({'title': title, 'content': snippet, 'url': url})
        return results
    except Exception:
        return []


def search_searxng(query, max_results=5):
    """Search using a public SearXNG instance as fallback (no API key needed)."""
    # List of reliable public SearXNG instances
    instances = [
        'https://searx.be',
        'https://search.mdosch.de',
        'https://searxng.world',
    ]
    for instance in instances:
        try:
            r = requests.get(
                f'{instance}/search',
                params={'q': query, 'format': 'json', 'language': 'en'},
                headers=BROWSER_HEADERS,
                timeout=12
            )
            if r.status_code == 200:
                data = r.json()
                results = []
                for item in data.get('results', [])[:max_results]:
                    results.append({
                        'title': item.get('title', ''),
                        'content': item.get('content', ''),
                        'url': item.get('url', '')
                    })
                if results:
                    return results
        except Exception:
            continue
    return []


def web_search(query):
    """Search the web: try DuckDuckGo HTML scrape first, then SearXNG fallback."""
    results = search_ddg_html(query)
    if not results:
        results = search_searxng(query)
    if not results:
        return None, []
    answer = results[0].get('content', '') if results else ''
    return answer.strip(), results


def build_reply(answer, results):
    """
    Build a structured JSON-serialisable reply with:
      - summary: first result snippet (cleaned)
      - sources: list of {title, snippet, url, domain}
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
        return jsonify({'type': 'error', 'message': 'Web search unavailable. All search providers failed.'})
    reply = build_reply(answer, results)
    return jsonify({'type': 'result', 'data': reply})


@app.route('/debug')
def debug():
    query = request.args.get('q', 'news Spain')
    try:
        answer, results = web_search(query)
        return jsonify({'answer': answer, 'results': results, 'count': len(results)})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'time': datetime.utcnow().isoformat()})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
