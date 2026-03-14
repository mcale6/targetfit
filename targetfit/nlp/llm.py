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

from targetfit.config import PROJECT_ROOT
from targetfit.helpers import truncate
from targetfit.log import setup_logger


logger = setup_logger(__name__)


class LLMError(Exception):
    """Raised when an LLM call fails."""


class ParseError(Exception):
    """Raised when parsing an LLM JSON response fails."""


# ── Agent prompt loading ────────────────────────────────────────────────────

def _load_agent_section(tag: str, path: str | None = None) -> str:
    """Load the markdown section for a given agent tag."""
    resolved = Path(path) if path else PROJECT_ROOT / "prompts.md"
    content = resolved.read_text(encoding="utf-8")
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
    m = re.search(r"System prompt:?\s*```(.*?)```", section, re.DOTALL | re.IGNORECASE)
    if not m:
        raise LLMError("System prompt block not found in prompts.md section")
    return m.group(1).strip()


# ── Ollama calls ────────────────────────────────────────────────────────────

def call_ollama(
    prompt: str,
    system: str,
    config: Dict[str, Any],
    *,
    json_mode: bool = False,
    model_override: str | None = None,
) -> str:
    """Call Ollama /api/generate and return the raw text response.

    When json_mode=True, requests strict JSON output via Ollama's format parameter.
    """
    base = config.get("ollama_url", "http://localhost:11434").rstrip("/")
    # Prefer a dedicated scoring model if configured, otherwise fall back to legacy 'model'.
    model = model_override or config.get("scoring_model") or config.get("model")
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
    if not text.strip():
        return [0.0] * dims

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

    # If the model returned an empty embedding, try a short retry with a
    # smaller prompt (some models or inputs may return empty vectors on long
    # inputs). If that still fails, fall back to a zero vector so indexing can
    # continue.
    if len(embedding) == 0:
        logger.warning("Embedding empty — retrying with shorter prompt")
        try:
            short_payload = {"model": model, "prompt": text[:512]}
            resp2 = requests.post(url, json=short_payload, timeout=120)
            if resp2.status_code == 200:
                data2 = resp2.json()
                embedding2 = data2.get("embedding")
                if embedding2 is None and "data" in data2:
                    first = (data2.get("data") or [{}])[0]
                    embedding2 = first.get("embedding")
                if isinstance(embedding2, list) and len(embedding2) > 0:
                    embedding = embedding2
        except requests.RequestException:
            logger.debug("Retry for embedding failed; will use zero vector")

    if len(embedding) != dims:
        logger.warning(
            "Embedding dims mismatch: expected %d, got %d", dims, len(embedding)
        )
        if len(embedding) == 0:
            embedding = [0.0] * dims
        elif len(embedding) < dims:
            embedding = embedding + [0.0] * (dims - len(embedding))
        else:
            embedding = embedding[:dims]

    return [float(x) for x in embedding]


# ── JSON parsing ────────────────────────────────────────────────────────────

def _clean_json_string(text: str) -> str:
    """Fix common LLM JSON mistakes: trailing commas, comments, unquoted keys."""
    # Strip single-line comments (// ...).
    cleaned = re.sub(r'//[^\n]*', '', text)
    # Strip multi-line comments (/* ... */).
    cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
    # Remove trailing commas before } or ].
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    # Replace single-quoted strings with double-quoted.
    # Only do this if there are no double-quoted strings (to avoid breaking valid JSON).
    if '"' not in cleaned and "'" in cleaned:
        cleaned = cleaned.replace("'", '"')
    return cleaned


def parse_json_response(text: str) -> Any:
    """Parse JSON from an LLM response with robust handling.

    Tries multiple strategies in order:
    1. Direct parse (works with Ollama format='json')
    2. Strip markdown fences
    3. Clean common LLM mistakes (trailing commas, comments)
    4. Extract first JSON object/array substring
    5. Clean + extract combined
    """
    raw = text.strip()

    # 1) Direct parse.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2) Strip markdown fences.
    fenced = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
    try:
        return json.loads(fenced)
    except json.JSONDecodeError:
        pass

    # 3) Clean common mistakes then parse.
    cleaned = _clean_json_string(fenced)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 4) Extract first JSON object/array substring.
    for source in (fenced, cleaned):
        start = min(
            (i for i in (source.find("{"), source.find("[")) if i != -1),
            default=-1,
        )
        if start != -1:
            candidate = source[start:]
            end_brackets = [i for i in (candidate.rfind("}"), candidate.rfind("]")) if i != -1]
            if end_brackets:
                end = max(end_brackets) + 1
                candidate = _clean_json_string(candidate[:end].strip())
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass

    logger.warning("JSON parse failed — raw LLM response: %.500s", text)
    raise ParseError("Failed to parse JSON from LLM response.")


_STRIP_CHARS = " -\n\t\r\"'[]" + chr(0x201C) + chr(0x201D)


def _salvage_score_payload(text: str) -> Dict[str, Any] | None:
    """Best-effort recovery when the scorer returns prose or malformed JSON."""
    raw = (text or "").strip()
    if not raw:
        return None

    # Try to find score with various patterns.
    score_match = (
        re.search(r'"?score"?\s*[:=]\s*([0-9]*\.?[0-9]+)', raw, re.IGNORECASE)
        or re.search(r'\b(\d\.\d+)\s*/\s*1(?:\.0)?', raw)
        or re.search(r'\b([0-9]\d?)\s*(?:/\s*100|%)', raw)
    )
    summary_match = re.search(
        r'"?summary"?\s*[:=]\s*["\'\u201c]?(.+?)["\'\u201d]?(?:\n|$)',
        raw, re.IGNORECASE,
    )

    reasons: List[str] = []
    gaps: List[str] = []

    reasons_match = re.search(
        r'"?match_reasons"?\s*[:=]\s*(.+?)'
        r'(?:"?gaps"?\s*[:=]|"?summary"?\s*[:=]|$)',
        raw, re.IGNORECASE | re.DOTALL,
    )
    gaps_match = re.search(
        r'"?gaps"?\s*[:=]\s*(.+?)(?:"?summary"?\s*[:=]|$)',
        raw, re.IGNORECASE | re.DOTALL,
    )

    if reasons_match:
        reasons = [
            s for item in re.split(r'[,\n]', reasons_match.group(1))
            if (s := item.strip(_STRIP_CHARS))
        ]
    if gaps_match:
        gaps = [
            s for item in re.split(r'[,\n]', gaps_match.group(1))
            if (s := item.strip(_STRIP_CHARS))
        ]

    payload: Dict[str, Any] = {}
    if score_match:
        val = float(score_match.group(1))
        if val > 1.0:
            val = val / 100.0
        payload["score"] = min(max(val, 0.0), 1.0)
    if reasons:
        payload["match_reasons"] = reasons[:4]
    if gaps:
        payload["gaps"] = gaps[:3]
    if summary_match:
        payload["summary"] = summary_match.group(1).strip(_STRIP_CHARS)

    return payload if payload else None


# ── Scoring ─────────────────────────────────────────────────────────────────

def _repair_json_with_llm(broken: str, config: Dict[str, Any]) -> Dict[str, Any] | None:
    """Ask a small model to fix broken JSON output from the scorer."""
    repair_system = (
        "You are a JSON repair tool. The user will give you broken or malformed JSON. "
        "Return ONLY the corrected JSON object — no explanation, no markdown fences."
    )
    repair_prompt = (
        "Fix this JSON so it is valid. Keep the same keys and values. "
        'Required schema: {"score": float, "match_reasons": [str], "gaps": [str], "summary": str}\n\n'
        f"{broken}"
    )
    fallback_model = config.get("fallback_model")
    model = fallback_model or config.get("scoring_model") or config.get("model")
    try:
        resp = call_ollama(
            prompt=repair_prompt,
            system=repair_system,
            config=config,
            json_mode=True,
            model_override=model,
        )
        return parse_json_response(resp)
    except (LLMError, ParseError):
        return None


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

    parsed: Any = None
    raw_resp: str = ""
    fallback_model = config.get("fallback_model")
    primary_model = config.get("scoring_model") or config.get("model")

    # Attempt 1: primary model with json_mode.
    try:
        raw_resp = call_ollama(
            prompt=user_prompt,
            system=system_prompt,
            config=config,
            json_mode=True,
        )
        parsed = parse_json_response(raw_resp)
    except (LLMError, ParseError) as exc:
        logger.warning("score_job: primary model parse failed for %s: %s", job.get("title"), exc)

    # Attempt 2: if response was non-empty prose/broken JSON, try LLM repair.
    if parsed is None and raw_resp and raw_resp.strip():
        parsed = _repair_json_with_llm(raw_resp, config)
        if parsed is not None:
            logger.info("score_job: JSON repair succeeded for %s", job.get("title"))

    # Attempt 3: if response was empty/useless, retry with fallback model directly.
    if parsed is None and fallback_model and fallback_model != primary_model:
        try:
            raw_resp2 = call_ollama(
                prompt=user_prompt,
                system=system_prompt,
                config=config,
                json_mode=True,
                model_override=fallback_model,
            )
            parsed = parse_json_response(raw_resp2)
            if parsed is not None:
                logger.info("score_job: fallback model succeeded for %s", job.get("title"))
        except (LLMError, ParseError) as exc:
            logger.warning("score_job: fallback model failed for %s: %s", job.get("title"), exc)
            # Try salvage from whichever response had content.
            parsed = _salvage_score_payload(raw_resp2 if raw_resp2.strip() else raw_resp)

    # Attempt 4: regex salvage from raw response.
    if parsed is None and raw_resp:
        parsed = _salvage_score_payload(raw_resp)
        if parsed is not None:
            logger.info("score_job: regex salvage recovered score for %s", job.get("title"))

    # Build enriched result.
    enriched = dict(job)
    if isinstance(parsed, dict) and "score" in parsed:
        enriched["llm_score"] = min(max(float(parsed.get("score", 0.0) or 0.0), 0.0), 1.0)
        enriched["match_reasons"] = parsed.get("match_reasons") or []
        enriched["gaps"] = parsed.get("gaps") or []
        enriched["summary"] = parsed.get("summary") or ""
    else:
        logger.warning("score_job: all strategies failed for %s — using vector score", job.get("title"))
        enriched["llm_score"] = float(job.get("vector_score") or 0.0)
        enriched["match_reasons"] = []
        enriched["gaps"] = []
        enriched["summary"] = ""

    return enriched
