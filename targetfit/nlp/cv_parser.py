"""Extract structured job-search terms from a CV text using Ollama.

The returned SearchTerms object is used by url_builder to construct
search URLs that hit actual results pages instead of landing pages.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from targetfit.log import setup_logger
from targetfit.nlp.llm import LLMError, ParseError, call_ollama, parse_json_response


logger = setup_logger(__name__)


@dataclass
class SearchTerms:
    """Structured search profile extracted from a CV."""

    # 2-4 job title / role keywords the candidate is targeting.
    job_titles: List[str] = field(default_factory=list)

    # Technical/scientific domains (e.g. "drug discovery", "bioinformatics").
    domains: List[str] = field(default_factory=list)

    # Key technical skills worth searching for (e.g. "PyTorch", "RDKit").
    skills: List[str] = field(default_factory=list)

    # Ready-to-use query strings, ordered best-first.
    # url_builder uses these when constructing search URLs.
    queries: List[str] = field(default_factory=list)

    def best_query(self) -> str:
        """Return the single best search query, or a fallback."""
        return self.queries[0] if self.queries else (self.job_titles[0] if self.job_titles else "")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "job_titles": self.job_titles,
            "domains": self.domains,
            "skills": self.skills,
            "queries": self.queries,
        }


# ── Fallback in case the LLM is unavailable ─────────────────────────────────

_DEFAULT_TERMS = SearchTerms(
    job_titles=["data scientist", "computational biologist"],
    domains=["machine learning", "bioinformatics"],
    skills=["Python"],
    queries=["computational biologist", "data scientist bioinformatics"],
)

_SYSTEM_PROMPT = """\
You are a job search assistant. Given a candidate's CV text, extract a structured
search profile that will be used to build search URLs on company careers pages.

Return ONLY a valid JSON object with this exact schema:
{
  "job_titles":  [string],   // 2-4 job titles/roles the candidate is targeting
  "domains":     [string],   // 2-4 technical or scientific domains
  "skills":      [string],   // 3-6 key technical skills (tools, frameworks, languages)
  "queries":     [string]    // 3-5 short search strings (2-4 words each), best first
}

Rules:
- "queries" must be short and URL-friendly (no special characters).
- Order "queries" from most specific to most general.
- Focus on the candidate's strongest/most recent experience.
- Do NOT invent experience not in the CV.
- Return ONLY the JSON object. No preamble, no markdown fences.
"""


def extract_search_terms(cv_text: str, config: Dict[str, Any]) -> SearchTerms:
    """Parse the CV with Ollama and return a SearchTerms object.

    Falls back to _DEFAULT_TERMS if the LLM call fails, so the pipeline
    can still run with generic queries rather than crashing.
    """
    if not cv_text or not cv_text.strip():
        logger.warning("cv_parser: empty CV — using default search terms")
        return _DEFAULT_TERMS

    user_prompt = f"CV:\n\n{cv_text.strip()[:6000]}"  # cap to avoid huge prompts

    try:
        parsed = _call_and_parse_search_terms(user_prompt, config)
    except (LLMError, ParseError) as exc:
        logger.warning("cv_parser: LLM call failed (%s) — using default terms", exc)
        return _DEFAULT_TERMS

    if not isinstance(parsed, dict):
        logger.warning("cv_parser: unexpected response type — using default terms")
        return _DEFAULT_TERMS

    terms = SearchTerms(
        job_titles=_clean_list(parsed.get("job_titles")),
        domains=_clean_list(parsed.get("domains")),
        skills=_clean_list(parsed.get("skills")),
        queries=_clean_list(parsed.get("queries")),
    )

    # Guarantee at least one query even if the LLM returned empty lists.
    if not terms.queries and terms.job_titles:
        terms.queries = terms.job_titles[:3]
    if not terms.queries:
        return _DEFAULT_TERMS

    logger.info(
        "cv_parser: extracted %d queries: %s",
        len(terms.queries),
        ", ".join(f'"{q}"' for q in terms.queries),
    )
    return terms


def _call_and_parse_search_terms(user_prompt: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Call the LLM and return parsed JSON, with repair/fallback handling."""
    raw = call_ollama(
        prompt=user_prompt,
        system=_SYSTEM_PROMPT,
        config=config,
        json_mode=True,
    )

    try:
        parsed = parse_json_response(raw)
        if isinstance(parsed, dict):
            return parsed
    except ParseError:
        fallback_model = config.get("fallback_model")
        primary_model = config.get("scoring_model") or config.get("model")
        if fallback_model and fallback_model != primary_model:
            logger.info(
                "cv_parser: primary model returned non-JSON output; retrying with fallback model %s",
                fallback_model,
            )
            retry_raw = call_ollama(
                prompt=user_prompt,
                system=_SYSTEM_PROMPT,
                config=config,
                json_mode=True,
                model_override=fallback_model,
            )
            try:
                retry_parsed = parse_json_response(retry_raw)
                if isinstance(retry_parsed, dict):
                    return retry_parsed
            except ParseError:
                retry_salvaged = _salvage_terms_from_text(retry_raw)
                if retry_salvaged is not None:
                    logger.info("cv_parser: recovered structured terms from fallback model output")
                    return retry_salvaged

        salvaged = _salvage_terms_from_text(raw)
        if salvaged is not None:
            logger.info("cv_parser: recovered structured terms from non-JSON model output")
            return salvaged

        raise

    raise ParseError("CV parser returned a non-object response")


def _salvage_terms_from_text(text: str) -> Dict[str, List[str]] | None:
    """Best-effort recovery when the model returns prose instead of JSON."""
    raw = (text or "").strip()
    if not raw:
        return None

    lowered = raw.lower()
    result = {
        "job_titles": [],
        "domains": [],
        "skills": [],
        "queries": [],
    }

    extracted_job_titles = _extract_inline_list(
        raw,
        ["job titles", "job_title", "titles", "roles", "let's choose"],
    )
    extracted_domains = _extract_inline_list(raw, ["domains", "domain"]) 
    extracted_skills = _extract_inline_list(raw, ["skills", "skill", "tools", "frameworks"]) 
    extracted_queries = _extract_inline_list(raw, ["queries", "query", "search strings"]) 

    if extracted_job_titles:
        result["job_titles"] = extracted_job_titles[:4]
    if extracted_domains:
        result["domains"] = extracted_domains[:4]
    if extracted_skills:
        result["skills"] = extracted_skills[:6]
    if extracted_queries:
        result["queries"] = extracted_queries[:5]

    # Some models produce prose like: "The candidate is a hybrid X, Y, Z."
    if not result["job_titles"]:
        hybrid_match = re.search(r"candidate is (?:an?|the)?\s*(?:a )?hybrid\s+(.+?)(?:\.|\n)", lowered, re.IGNORECASE)
        if hybrid_match:
            raw_titles = re.split(r",|/| and ", hybrid_match.group(1))
            result["job_titles"] = _normalise_items(raw_titles)[:4]

    if result["job_titles"] and not result["queries"]:
        result["queries"] = [_to_query_string(item) for item in result["job_titles"][:3] if item]

    has_any = any(result.values())
    return result if has_any else None


def _extract_inline_list(text: str, labels: List[str]) -> List[str]:
    for label in labels:
        pattern = rf"{re.escape(label)}\s*:\s*(.+?)(?:\n\s*\n|\n[A-Z][^\n]*:|$)"
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        items = re.split(r",|;|\n|-\s+", match.group(1))
        normalised = _normalise_items(items)
        if normalised:
            return normalised
    return []


def _normalise_items(items: List[str]) -> List[str]:
    cleaned: List[str] = []
    seen: set[str] = set()
    for item in items:
        value = re.sub(r"^[\d\.)\-\s]+", "", str(item or "").strip())
        value = value.strip(" \t\n\r\"'")
        if not value:
            continue
        if len(value) < 3:
            continue
        if value.lower() in {"or", "and", "need", "strong experience"}:
            continue
        key = value.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(value)
    return cleaned


def _to_query_string(text: str) -> str:
    query = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
    query = re.sub(r"\s+", " ", query).strip().lower()
    return query


def _clean_list(value: Any) -> List[str]:
    """Normalise an LLM list field to a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if v and str(v).strip()]
