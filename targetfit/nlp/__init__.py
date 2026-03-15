"""NLP — Ollama LLM integration and CV parsing."""

from targetfit.models import SearchTerms
from targetfit.nlp.cv_parser import extract_search_terms
from targetfit.nlp.llm import (
    LLMError,
    ParseError,
    call_ollama,
    get_embedding,
    parse_json_response,
    score_job,
)

__all__ = [
    "LLMError",
    "ParseError",
    "SearchTerms",
    "call_ollama",
    "extract_search_terms",
    "get_embedding",
    "parse_json_response",
    "score_job",
]
