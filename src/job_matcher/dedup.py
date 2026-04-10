"""Canonical job ID computation and normalizers."""

import hashlib
import re
from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel

from job_matcher.models import Job, JobSource, RawJob

_GENDER_MARKERS = re.compile(r"\s*\([mfwd]/[mfwd]/[mfwd]\)", re.IGNORECASE)
_SENIORITY_PREFIXES = re.compile(
    r"\b(?:sr\.?|senior|jr\.?|junior)\b", re.IGNORECASE
)
_TRAILING_TAGS = re.compile(
    r"\s*[-\u2013]\s*(?:remote|hybrid|onsite|on-site)\s*$"
    r"|\s*\((?:remote|hybrid|onsite|on-site)\)\s*$"
    r"|\s*\[(?:remote|hybrid|onsite|on-site)\]\s*$",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_NON_ALNUM_UNICODE = re.compile(r"[^\w\s]", re.UNICODE)
_MULTI_SPACE = re.compile(r"\s+")

_LEGAL_SUFFIXES = re.compile(
    r"\b(?:"
    r"sp\.\s*z\s*o\.?\s*o\.?\s*(?:sp\.\s*k\.?)?"
    r"|gmbh|ltd\.?|ag|s\.a\.|s\.r\.l\.|llc|inc\.?|corp\.?|b\.v\.|bv|n\.v\.|nv"
    r")\s*$",
    re.IGNORECASE,
)

_POSTAL_CODE = re.compile(r"\b\d{4,6}\b|\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)
_COUNTRY_NAMES = re.compile(
    r"\b(?:poland|germany|switzerland|united kingdom|uk|netherlands)\b",
    re.IGNORECASE,
)

_CURRENCY_SYMBOLS = {"€": "EUR", "£": "GBP", "$": "USD"}
_CURRENCY_NAMES = {"eur": "EUR", "usd": "USD", "pln": "PLN", "chf": "CHF", "gbp": "GBP"}
_PERIOD_MAP = {
    "h": "hour", "hour": "hour", "hourly": "hour",
    "d": "day", "day": "day", "daily": "day",
    "m": "month", "month": "month", "monthly": "month",
    "y": "year", "year": "year", "yearly": "year", "annual": "year", "annually": "year",
}
_EMPLOYMENT_MAP = {
    "b2b": "b2b",
    "permanent": "permanent",
    "contract": "contract",
    "internship": "internship",
    "full-time": "permanent",
    "full time": "permanent",
    "part-time": "contract",
}
_REMOTE_MAP = {
    "remote": "remote",
    "hybrid": "hybrid",
    "onsite": "onsite",
    "on-site": "onsite",
    "on_site": "onsite",
    "office": "onsite",
}


class SalaryInfo(BaseModel):
    min: float | None
    max: float | None
    currency: str | None
    period: str | None


def normalize_title(title: str) -> str:
    t = title.lower()
    t = _GENDER_MARKERS.sub("", t)
    t = _SENIORITY_PREFIXES.sub("", t)
    t = _TRAILING_TAGS.sub("", t)
    t = _NON_ALNUM.sub("", t)
    t = _MULTI_SPACE.sub(" ", t).strip()
    return t


def normalize_company(company: str) -> str:
    c = company.lower()
    c = _LEGAL_SUFFIXES.sub("", c)
    c = _NON_ALNUM.sub("", c)
    c = _MULTI_SPACE.sub(" ", c).strip()
    return c


def normalize_location(location: str | None) -> str:
    if not location:
        return ""
    loc = location.lower()
    loc = _POSTAL_CODE.sub("", loc)
    loc = _COUNTRY_NAMES.sub("", loc)
    # Take first comma-separated part (usually the city)
    loc = loc.split(",")[0]
    loc = _NON_ALNUM_UNICODE.sub(" ", loc)
    loc = _MULTI_SPACE.sub(" ", loc).strip()
    return loc


def compute_canonical_id(title: str, company: str, location: str | None) -> str:
    norm_t = normalize_title(title)
    norm_c = normalize_company(company)
    norm_l = normalize_location(location)
    normalized = f"{norm_t}|{norm_c}|{norm_l}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def parse_salary(raw: str | None) -> SalaryInfo:
    if not raw:
        return SalaryInfo(min=None, max=None, currency=None, period=None)

    text = raw.strip()
    currency = None
    period = None

    # Detect currency symbol at start
    for sym, cur in _CURRENCY_SYMBOLS.items():
        if sym in text:
            currency = cur
            text = text.replace(sym, " ")
            break

    # Detect currency name
    if not currency:
        for name, cur in _CURRENCY_NAMES.items():
            if re.search(rf"\b{name}\b", text, re.IGNORECASE):
                currency = cur
                text = re.sub(rf"\b{name}\b", " ", text, flags=re.IGNORECASE)
                break

    # Detect period
    for token, per in _PERIOD_MAP.items():
        if re.search(rf"\b{re.escape(token)}\b", text, re.IGNORECASE):
            period = per
            text = re.sub(rf"\b{re.escape(token)}\b", " ", text, flags=re.IGNORECASE)
            break
    # Also check /h, /d patterns
    period_slash = re.search(r"/\s*([a-z]+)", text, re.IGNORECASE)
    if period_slash and not period:
        p = period_slash.group(1).lower()
        period = _PERIOD_MAP.get(p)
        if period:
            text = text[: period_slash.start()]

    # Extract numbers
    text = text.replace(",", "")
    numbers = re.findall(r"(\d+(?:\.\d+)?)\s*k?", text, re.IGNORECASE)
    k_markers = re.findall(r"\d+(?:\.\d+)?\s*(k)", text, re.IGNORECASE)

    if not numbers:
        if not currency and not period:
            return SalaryInfo(min=None, max=None, currency=None, period=None)
        return SalaryInfo(min=None, max=None, currency=currency, period=period)

    values = []
    for i, n in enumerate(numbers):
        v = float(n)
        if (
            (i < len(k_markers) and k_markers[i].lower() == "k")
            or (
                "k" in raw.lower()
                and v < 1000
                and re.search(rf"{re.escape(n)}\s*k", raw, re.IGNORECASE)
            )
        ):
            v *= 1000
        values.append(v)

    sal_min = values[0] if len(values) >= 1 else None
    sal_max = values[1] if len(values) >= 2 else None

    return SalaryInfo(min=sal_min, max=sal_max, currency=currency, period=period)


def map_employment_type(raw: str | None) -> str:
    if not raw:
        return "unknown"
    return _EMPLOYMENT_MAP.get(raw.lower().strip(), "unknown")


def map_remote_type(raw: str | None) -> str:
    if not raw:
        return "unknown"
    return _REMOTE_MAP.get(raw.lower().strip(), "unknown")


def canonicalize_raw(raw: RawJob, now: datetime) -> tuple[Job, JobSource]:
    salary = parse_salary(raw.salary_raw)
    job_id = compute_canonical_id(raw.title, raw.company, raw.location)

    job = Job(
        id=job_id,
        title=raw.title,
        company=raw.company,
        location=raw.location,
        description=raw.description,
        salary_min=salary.min,
        salary_max=salary.max,
        salary_currency=cast(
            Literal["EUR", "USD", "PLN", "CHF", "GBP"] | None, salary.currency
        ),
        salary_period=cast(
            Literal["hour", "day", "month", "year"] | None, salary.period
        ),
        employment_type=cast(
            Literal["b2b", "permanent", "contract", "internship", "unknown"],
            map_employment_type(raw.employment_type_raw),
        ),
        remote_type=cast(
            Literal["remote", "hybrid", "onsite", "unknown"],
            map_remote_type(raw.remote_type_raw),
        ),
        seniority="unknown",
        posted_at=None,
        first_seen_at=now,
        last_seen_at=now,
        scraped_at=now,
    )

    source = JobSource(
        job_id=job_id,
        platform=raw.platform,
        platform_job_id=raw.platform_job_id,
        url=raw.url,
        scraped_at=now,
        raw=raw.raw,
    )

    return job, source
