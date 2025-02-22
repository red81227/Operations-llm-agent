from langchain_community.tools.tavily_search import TavilySearchResults
import os 
os.environ['TAVILY_API_KEY'] = "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"
search = TavilySearchResults(max_results=3)