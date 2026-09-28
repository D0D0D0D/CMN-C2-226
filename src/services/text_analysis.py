"""AgentCore Platform v1.0 — CMN-C2-226 deterministic text-analysis helpers.

Pure, dependency-free, side-effect-free functions used by the QA-audit nodes.
No LLM, no credentials, no I/O — keeps citation/consistency checks deterministic
and reproducible (the moat: citation integrity is verified by deterministic
matching against RAG source chunks, not by an LLM-as-judge).
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Citation markers: [1], [2], or [chunk_id] style references inside the response.
_CITATION_RE = re.compile(r"\[([A-Za-z0-9_\-]+)\]")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")

_STOPWORDS = frozenset(
    "the a an and or of to in on for is are was were be been with as at by it this that "
    "these those from we you they he she i".split()
)


def tokenize(text: str) -> set[str]:
    """Lowercase content tokens (stopwords removed)."""
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS}


def jaccard(a: str, b: str) -> float:
    """Jaccard similarity of the content tokens of two strings (0.0-1.0)."""
    ta, tb = tokenize(a), tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def overlap_ratio(claim: str, source: str) -> float:
    """Fraction of the claim's content tokens that appear in the source (0.0-1.0)."""
    tc, ts = tokenize(claim), tokenize(source)
    if not tc:
        return 0.0
    return len(tc & ts) / len(tc)


def split_claims(text: str) -> list[str]:
    """Split a response into claim-sized units (sentences)."""
    if not text or not text.strip():
        return []
    parts = [s.strip() for s in _SENT_SPLIT_RE.split(text) if s and s.strip()]
    return parts


def extract_citations(text: str) -> list[str]:
    """Extract citation markers (e.g. [1], [chunk_3]) in order of appearance."""
    if not text:
        return []
    return _CITATION_RE.findall(text)
