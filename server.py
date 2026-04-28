from flask import Flask, send_from_directory, request, jsonify
import os
import asyncio
import json
import sys
import logging
from aisens_search import aisens_search

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='web', static_url_path='')

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
        
        # Call AISENS search synchronously
        result = asyncio.run(aisens_search(query))
        
        # Format response
        response_data = {
            'summary': result.get('summary', ''),
            'sources': []
        }
        
        # Add sources if available
        if 'sources' in result:
            for source in result['sources']:
                response_data['sources'].append({
                    'title': source.get('title', ''),
                    'url': source.get('url', ''),
                    'snippet': source.get('snippet', ''),
                    'domain': source.get('domain', '')
                })
        
        return jsonify({'type': 'result', 'data': response_data})
        
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        return jsonify({'type': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
