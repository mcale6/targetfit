"""Pydantic models for structured data validation across the pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Job(BaseModel):
    """Canonical job record used throughout the pipeline."""

    company: str
    title: str
    location: str | None = None
    url: str | None = None
    description: str | None = None
    date_posted: str | None = None


class ExtractedJob(BaseModel):
    """Job data as returned by the LLM JOB_EXTRACTOR agent."""

    title: str
    company: str | None = None
    location: str | None = None
    description: str | None = None
    date_posted: str | None = None


class ScoreResult(BaseModel):
    """LLM scoring result from the SCORER agent."""

    score: float = Field(ge=0.0, le=1.0)
    match_reasons: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    summary: str = ""


class SearchTerms(BaseModel):
    """Structured search profile extracted from a CV."""

    job_titles: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)

    def best_query(self) -> str:
        """Return the single best search query, or a fallback."""
        return self.queries[0] if self.queries else (
            self.job_titles[0] if self.job_titles else ""
        )
