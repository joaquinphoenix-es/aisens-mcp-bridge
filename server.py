from flask import Flask, send_from_directory, request, jsonify
import os
from flask_cors import CORS
import requests
import logging
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get Tavily API key from environment
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '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')

app = Flask(__name__, static_folder='web', static_url_path='')
CORS(app)

@app.route('/')
def serve_index():
    return send_from_directory('web', 'index.html')

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        query = data.get('message', '')
        
        if not query:
            return jsonify({'type': 'error', 'message': 'No message provided'}), 400
        
        logger.info(f"Processing query: {query}")
        
        # Call Tavily API directly
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
        
        tavily_data = response.json()
        
        # Format response
        response_data = {
            'summary': tavily_data.get('answer', 'No answer available'),
            'sources': []
        }
        
        # Add sources if available
        results = tavily_data.get('results', [])
        for result in results:
            url = result.get('url', '')
            domain = ''
            if url:
                try:
                    parsed = urlparse(url)
                    domain = parsed.netloc
                except:
                    pass
            
            response_data['sources'].append({
                'title': result.get('title', 'Untitled'),
                'url': url,
                'snippet': result.get('content', '')[:300],
                'domain': domain
            })
        
        # If no answer, use first result content
        if not response_data['summary'] and results:
            response_data['summary'] = results[0].get('content', '')[:500]
        
        return jsonify({'type': 'result', 'data': response_data})
        
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        return jsonify({
            'type': 'error', 
            'message': f'Error: {str(e)}'
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
