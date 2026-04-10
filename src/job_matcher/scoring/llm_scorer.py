"""Async Claude Haiku semantic scoring."""

import json
import logging

import anthropic
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from job_matcher.cost_tracker import CostTracker
from job_matcher.models import CvVersion, Job

logger = logging.getLogger(__name__)

_LLM_RETRY = retry(
    retry=retry_if_exception_type(
        (anthropic.RateLimitError, anthropic.InternalServerError)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    reraise=True,
)


class LlmScoreResult(BaseModel):
    semantic_score: float
    reasoning: str
    green_flags: list[str]
    red_flags: list[str]
    input_tokens: int
    output_tokens: int


def build_scoring_prompt(job: Job, cv: CvVersion, keywords: list[str]) -> str:
    salary_display = "Not specified"
    if job.salary_min is not None:
        salary_display = f"{job.salary_min}"
        if job.salary_max is not None:
            salary_display += f"-{job.salary_max}"
        if job.salary_currency:
            salary_display += f" {job.salary_currency}"
        if job.salary_period:
            salary_display += f"/{job.salary_period}"

    return f"""You are a senior technical recruiter evaluating whether a candidate's experience genuinely fits a role.

This is a SEMANTIC fit evaluation. Keyword matching is computed separately in code.
Focus on whether the candidate's actual experience, seniority, and domain background match the role.

<candidate_cv>
{cv.content}
</candidate_cv>

<job_posting>
Title: {job.title}
Company: {job.company}
Location: {job.location}
Employment: {job.employment_type}
Remote: {job.remote_type}
Salary: {salary_display}

Description:
{job.description}
</job_posting>

<must_have_keywords_from_jd>
{', '.join(keywords)}
</must_have_keywords_from_jd>

Score semantic fit on 0.0 to 1.0:
- 1.0 = candidate's core experience is exactly what the role needs, at the right seniority, in a relevant domain
- 0.8 = strong experience match, minor domain or seniority gap
- 0.6 = adjacent experience, candidate could grow into the role
- 0.4 = significant gap in depth, domain, or seniority
- 0.2 = candidate has only tangentially related experience
- 0.0 = fundamentally different experience profile

Focus on:
- Does the CV demonstrate production experience with the key tools, not just passing mentions?
- Does seniority (years + scope of ownership) match what the role expects?
- Is the domain experience (fintech, insurtech, healthcare, etc.) relevant?
- Is the candidate's trajectory aligned with this role, or is it a sideways move into unfamiliar territory?
- Does the contract structure match (B2B vs permanent)?

Output ONLY valid JSON, no prose or markdown fences:
{{"semantic_score": 0.00, "reasoning": "2-3 sentences explaining semantic fit, not keyword presence", "green_flags": ["substantive", "experience", "matches"], "red_flags": ["real", "experience", "gaps"]}}"""


def parse_scoring_response(text: str) -> LlmScoreResult:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace != -1 and last_brace != -1:
            cleaned = cleaned[first_brace : last_brace + 1]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse scoring response: {e}\nResponse: {cleaned[:500]}"
        ) from e

    return LlmScoreResult(
        semantic_score=float(data.get("semantic_score", 0.0)),
        reasoning=str(data.get("reasoning", "")),
        green_flags=data.get("green_flags", []),
        red_flags=data.get("red_flags", []),
        input_tokens=0,
        output_tokens=0,
    )


class LlmScorer:
    def __init__(self, client, model: str, cost_tracker: CostTracker):
        self._client = client
        self._model = model
        self._cost_tracker = cost_tracker

    async def _call_llm(self, prompt: str):
        """Call Anthropic API with tenacity retry on rate limits / 5xx."""

        @_LLM_RETRY
        async def _inner():
            return await self._client.messages.create(
                model=self._model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

        return await _inner()

    async def score_one(
        self,
        job: Job,
        cv: CvVersion,
        extracted_keywords: list[str],
    ) -> LlmScoreResult:
        prompt = build_scoring_prompt(job, cv, extracted_keywords)

        for attempt in range(2):
            try:
                response = await self._call_llm(prompt)
                text = response.content[0].text
                usage = response.usage
                result = parse_scoring_response(text)
                result.input_tokens = usage.input_tokens
                result.output_tokens = usage.output_tokens

                self._cost_tracker.record(
                    command="score",
                    operation="semantic_scoring",
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    job_id=job.id,
                    cv_id=cv.id,
                )
                return result
            except ValueError:
                if attempt == 1:
                    logger.warning(
                        "LLM parse error on both attempts for job=%s cv=%s",
                        job.id, cv.id,
                    )
                    return LlmScoreResult(
                        semantic_score=0.0,
                        reasoning="LLM parse error on both attempts",
                        green_flags=[],
                        red_flags=[],
                        input_tokens=0,
                        output_tokens=0,
                    )
                logger.info("Retrying LLM call for job=%s cv=%s", job.id, cv.id)

        # Unreachable but satisfies type checker
        raise RuntimeError("Unreachable")

