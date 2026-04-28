import os
import json
from flask import Flask, request, jsonify, send_from_directory
import requests

app = Flask(__name__, static_folder='.')

TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_BASE_URL = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
MODEL = os.environ.get('MODEL', 'gpt-4o-mini')


def web_search(query):
    """Search the web using Tavily."""
    if not TAVILY_API_KEY:
        return None
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
            timeout=10
        )
        data = r.json()
        return data.get('answer') or '\n'.join(
            [f"- {r['title']}: {r['content'][:200]}" for r in data.get('results', [])]
        )
    except Exception as e:
        return None


def ask_llm(user_message, search_context=None):
    """Call the LLM with optional search context."""
    if not OPENAI_API_KEY:
        if search_context:
            return f"AISENS found this: {search_context}"
        return "AISENS is running but no LLM API key is configured. Please set OPENAI_API_KEY."

    system_prompt = """You are AISENS, a helpful AI assistant with internet access.
You are concise, accurate, and friendly. You always respond in the same language the user writes in."""

    messages = [{"role": "system", "content": system_prompt}]

    if search_context:
        messages.append({
            "role": "system",
            "content": f"Web search results for context:\n{search_context}"
        })

    messages.append({"role": "user", "content": user_message})

    try:
        r = requests.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL,
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.7
            },
            timeout=30
        )
        data = r.json()
        return data['choices'][0]['message']['content']
    except Exception as e:
        return f"Error contacting LLM: {str(e)}"


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'reply': 'Please send a message.'})

    # Try web search first for factual/current queries
    search_context = web_search(user_message)

    # Get LLM response
    reply = ask_llm(user_message, search_context)

    return jsonify({'reply': reply})


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'aisens-web'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
