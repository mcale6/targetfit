"""Ollama integration for embeddings and LLM scoring.

Job extraction is now handled by ScrapeGraphAI (see scrape.py).
This module provides:
- call_ollama(): raw LLM generation (used by the SCORER agent)
- get_embedding(): embedding vectors via Ollama
- score_job(): CV-to-job match scoring via the SCORER agent
- parse_json_response(): robust JSON parsing from LLM output
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import requests

from utils import setup_logger, truncate


logger = setup_logger(__name__)


class LLMError(Exception):
    """Raised when an LLM call fails."""


class ParseError(Exception):
    """Raised when parsing an LLM JSON response fails."""


# ── Agent prompt loading ────────────────────────────────────────────────────

def _load_agent_section(tag: str, path: str = "AGENTS.md") -> str:
    """Load the markdown section for a given agent tag."""
    content = Path(path).read_text(encoding="utf-8")
    pattern = rf"^## \[{re.escape(tag)}\]\s*$"
    lines = content.splitlines()

    start_idx = None
    for i, line in enumerate(lines):
        if re.match(pattern, line.strip()):
            start_idx = i
            break
    if start_idx is None:
        raise LLMError(f"Agent section [{tag}] not found in {path}")

    # collect until next '## [' section or end of file
    body_lines: List[str] = []
    for line in lines[start_idx + 1 :]:
        if line.strip().startswith("## [") and line.strip().endswith("]"):
            break
        body_lines.append(line)
    return "\n".join(body_lines)


def _extract_system_prompt(section: str) -> str:
    """Extract the system prompt block from a section."""
    m = re.search(r"System prompt\s*```(.*?)```", section, re.DOTALL | re.IGNORECASE)
    if not m:
        raise LLMError("System prompt block not found in AGENTS.md section")
    return m.group(1).strip()


# ── Ollama calls ────────────────────────────────────────────────────────────

def call_ollama(
    prompt: str,
    system: str,
    config: Dict[str, Any],
    *,
    json_mode: bool = False,
) -> str:
    """Call Ollama /api/generate and return the raw text response.

    When json_mode=True, requests strict JSON output via Ollama's format parameter.
    """
    base = config.get("ollama_url", "http://localhost:11434").rstrip("/")
    # Prefer a dedicated scoring model if configured, otherwise fall back to legacy 'model'.
    model = config.get("scoring_model") or config.get("model")
    if not model:
        raise LLMError(
            "Scoring model not configured (config['scoring_model'] or config['model'])"
        )

    url = f"{base}/api/generate"
    logger.debug(
        "call_ollama(model=%s, json_mode=%s, base=%s, prompt_chars=%d)",
        model,
        json_mode,
        base,
        len(prompt),
    )
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
    }
    if json_mode:
        payload["format"] = "json"
    try:
        resp = requests.post(url, json=payload, timeout=120)
    except requests.RequestException as exc:
        raise LLMError(f"Ollama request error: {exc}") from exc

    if resp.status_code != 200:
        raise LLMError(f"Ollama returned status {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    text = data.get("response")
    if text is None:
        raise LLMError("Ollama response missing 'response' field")
    return text


def get_embedding(text: str, config: Dict[str, Any]) -> List[float]:
    """Call Ollama /api/embeddings and return embedding vector."""
    base = config.get("ollama_url", "http://localhost:11434").rstrip("/")
    model = config.get("embedding_model")
    dims = int(config.get("embedding_dims", 768))
    if not model:
        raise LLMError("Embedding model not configured (config['embedding_model'])")

    max_chars = int(config.get("max_description_chars", 4000))
    text = truncate(text or "", max_chars)

    url = f"{base}/api/embeddings"
    logger.debug(
        "get_embedding(model=%s, base=%s, dims=%d, text_chars=%d)",
        model,
        base,
        dims,
        len(text),
    )
    payload = {"model": model, "prompt": text}

    try:
        resp = requests.post(url, json=payload, timeout=120)
    except requests.RequestException as exc:
        raise LLMError(f"Ollama embeddings request error: {exc}") from exc

    if resp.status_code != 200:
        raise LLMError(
            f"Ollama embeddings returned status {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    # Ollama may return {"embedding": [...]} or {"data": [{"embedding": [...]}]}
    embedding = data.get("embedding")
    if embedding is None and "data" in data:
        first = (data.get("data") or [{}])[0]
        embedding = first.get("embedding")

    if not isinstance(embedding, list):
        raise LLMError("Embedding field missing or invalid in response")

    if len(embedding) != dims:
        logger.warning(
            "Embedding dims mismatch: expected %d, got %d", dims, len(embedding)
        )
    return [float(x) for x in embedding]


# ── JSON parsing ────────────────────────────────────────────────────────────

def parse_json_response(text: str) -> Any:
    """Parse JSON from an LLM response with robust handling.

    Prefers strict JSON mode outputs from Ollama but falls back to:
    - stripping ```json ... ``` fences
    - extracting the first top-level JSON object/array substring
    """
    raw = text.strip()

    # 1) Direct parse (works with Ollama format='json').
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2) Strip markdown fences.
    fenced = re.sub(r"```json\s*", "", raw, flags=re.IGNORECASE)
    fenced = re.sub(r"```\s*", "", fenced).strip()
    try:
        return json.loads(fenced)
    except json.JSONDecodeError:
        pass

    # 3) Fallback: grab the first plausible JSON substring.
    start = min(
        (i for i in (fenced.find("["), fenced.find("{")) if i != -1),
        default=-1,
    )
    if start != -1:
        candidate = fenced[start:]
        end_brackets = [i for i in (candidate.rfind("]"), candidate.rfind("}")) if i != -1]
        if end_brackets:
            end = max(end_brackets) + 1
            candidate = candidate[:end].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    logger.debug("Raw LLM response that failed to parse: %s", text)
    raise ParseError("Failed to parse JSON from LLM response.")


# ── Scoring ─────────────────────────────────────────────────────────────────

def score_job(job: Dict[str, Any], cv: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Score a single job against the CV using the SCORER agent."""
    try:
        section = _load_agent_section("SCORER")
        system_prompt = _extract_system_prompt(section)
    except LLMError as exc:
        logger.error("Failed to load SCORER prompt: %s", exc)
        return job

    description = job.get("description") or ""
    max_chars = int(config.get("max_description_chars", 4000))
    description_trunc = truncate(description, max_chars)

    user_prompt = (
        f"JOB TITLE: {job.get('title')}\n"
        f"COMPANY: {job.get('company')}\n"
        f"LOCATION: {job.get('location')}\n\n"
        f"JOB DESCRIPTION:\n{description_trunc}\n\n"
        f"---\n\nCANDIDATE CV:\n{cv}"
    )

    try:
        resp = call_ollama(
            prompt=user_prompt,
            system=system_prompt,
            config=config,
            json_mode=True,
        )
        parsed = parse_json_response(resp)
    except (LLMError, ParseError) as exc:
        logger.warning("score_job failed for %s: %s", job.get("title"), exc)
        return job

    if not isinstance(parsed, dict):
        logger.warning("SCORER returned non-object for %s", job.get("title"))
        return job

    enriched = dict(job)
    enriched["llm_score"] = float(parsed.get("score", 0.0) or 0.0)
    enriched["match_reasons"] = parsed.get("match_reasons") or []
    enriched["gaps"] = parsed.get("gaps") or []
    enriched["summary"] = parsed.get("summary") or ""
    return enriched
