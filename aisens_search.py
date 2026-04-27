from mcp.server.fastmcp import FastMCP
import logging
import requests
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('aisens_search')

TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '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')

mcp = FastMCP('AISENS Web Search')

@mcp.tool()
def web_search(keywords: str) -> dict:
    """Search the internet for real-time information. Always use this for current news, prices, weather, sports, stocks, or any recent event. Parameter keywords is the search query."""
    try:
        r = requests.post(
            'https://api.tavily.com/search',
            json={
                'api_key': TAVILY_API_KEY,
                'query': keywords,
                'search_depth': 'basic',
                'max_results': 3,
                'include_answer': True
            },
            timeout=10
        )
        data = r.json()
        answer = data.get('answer', '')
        results = data.get('results', [])
        if not answer and results:
            answer = results[0].get('content', '')[:500]
        logger.info(f'Search: {keywords} -> {answer[:80]}')
        return {'success': True, 'result': answer[:900]}
    except Exception as e:
        logger.error(f'Error: {e}')
        return {'success': False, 'result': str(e)}

if __name__ == '__main__':
    mcp.run(transport='stdio')
