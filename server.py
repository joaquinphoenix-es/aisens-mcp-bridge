from flask import Flask, send_from_directory, request, jsonify
import os
from flask_cors import CORS
import requests
import logging
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get Tavily API key from environment (Railway variable takes priority)
TAVILY_API_KEY = os.environ.get(
    'TAVILY_API_KEY',
    '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'
)

app = Flask(__name__, static_folder='web', static_url_path='')
CORS(app)


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

        logger.info(f"Processing query: {query}")

        # Call Tavily API
        response = requests.post(
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
        response.raise_for_status()
        tavily_data = response.json()

        # Build summary
        summary = tavily_data.get('answer', '')
        results = tavily_data.get('results', [])

        # Fallback: use first result if no direct answer
        if not summary and results:
            summary = results[0].get('content', '')[:500]

        if not summary:
            summary = 'No results found for your query.'

        # Build sources list
        sources = []
        for result in results:
            url = result.get('url', '')
            domain = ''
            if url:
                try:
                    domain = urlparse(url).netloc
                except Exception:
                    pass
            sources.append({
                'title': result.get('title', 'Untitled'),
                'url': url,
                'snippet': result.get('content', '')[:300],
                'domain': domain
            })

        return jsonify({
            'type': 'result',
            'data': {
                'summary': summary,
                'sources': sources
            }
        })

    except requests.exceptions.Timeout:
        logger.error("Tavily API timeout")
        return jsonify({'type': 'error', 'message': 'Search timed out. Please try again.'}), 504

    except requests.exceptions.HTTPError as e:
        logger.error(f"Tavily HTTP error: {e}")
        return jsonify({'type': 'error', 'message': f'Search API error: {e}'}), 502

    except Exception as e:
        logger.error(f"Error processing request: {e}")
        return jsonify({'type': 'error', 'message': f'Error: {str(e)}'}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
