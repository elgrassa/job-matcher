"""Mechanical keyword match against CV text."""

import re

from pydantic import BaseModel


class KeywordMatchResult(BaseModel):
    score: float
    required: list[str]
    matched: list[str]
    missing: list[str]


def compute_keyword_match(required: list[str], cv_text: str) -> KeywordMatchResult:
    """Match required keywords against CV text. Returns score = matched/total."""
    if not required:
        return KeywordMatchResult(score=0.0, required=[], matched=[], missing=[])

    matched: list[str] = []
    missing: list[str] = []
    cv_lower = cv_text.lower()

    for kw in required:
        year_req = _is_year_requirement(kw)
        if year_req is not None:
            cv_years = _extract_max_years_from_cv(cv_text)
            if cv_years >= year_req:
                matched.append(kw)
            else:
                missing.append(kw)
        elif _keyword_matches(kw, cv_lower):
            matched.append(kw)
        else:
            missing.append(kw)

    score = len(matched) / len(required)
    return KeywordMatchResult(
        score=round(score, 4),
        required=required,
        matched=matched,
        missing=missing,
    )


def _is_year_requirement(kw: str) -> int | None:
    """Return the required year count, or None if not a year requirement."""
    m = re.search(r"(\d+)\+?\s*years?", kw, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _extract_max_years_from_cv(cv_text: str) -> int:
    """Find max 'N years' pattern in CV, return int, default 0."""
    matches = re.findall(r"(\d+)\+?\s*years?", cv_text, re.IGNORECASE)
    if not matches:
        return 0
    return max(int(m) for m in matches)


def _normalize_for_match(s: str) -> str:
    """Lowercase, remove /, -, _ for CI/CD-style matching."""
    return re.sub(r"[/\-_]", "", s.lower())


def _keyword_matches(kw: str, cv_lower: str) -> bool:
    """Check if keyword matches in CV text, handling CI/CD variants."""
    kw_lower = kw.lower()

    # Try exact word-boundary match first
    pattern = r"\b" + re.escape(kw_lower) + r"\b"
    if re.search(pattern, cv_lower):
        return True

    # Try normalized match (handles CI/CD vs CICD vs CI-CD)
    kw_norm = _normalize_for_match(kw_lower)
    cv_norm = _normalize_for_match(cv_lower)
    return bool(kw_norm and re.search(r"\b" + re.escape(kw_norm) + r"\b", cv_norm))
