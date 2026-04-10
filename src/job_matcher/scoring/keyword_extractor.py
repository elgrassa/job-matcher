"""LLM-based keyword extraction from job descriptions."""

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime

from job_matcher.cost_tracker import CostTracker
from job_matcher.models import JdKeywords, Job

logger = logging.getLogger(__name__)


def build_extraction_prompt(job: Job) -> str:
    return f"""You are parsing a job posting to extract the must-have technical requirements.

<job_posting>
Title: {job.title}
Company: {job.company}

Description:
{job.description}
</job_posting>

Extract ONLY explicit technical must-haves that a CV would need to mention. Include:
- Programming languages (e.g., "java", "python", "typescript")
- Frameworks and libraries (e.g., "cypress", "playwright", "spring boot")
- Tools and platforms (e.g., "azure devops", "kubernetes", "jenkins")
- Methodologies and practices (e.g., "ci/cd", "tdd", "agile")
- Years of experience requirements (e.g., "5+ years", "10+ years")
- Domain requirements if explicitly mentioned (e.g., "insurance", "fintech", "healthcare")
- Certifications if required (e.g., "istqb", "aws certified")

DO NOT include:
- Soft skills ("communication", "teamwork", "problem solving")
- Generic phrases ("attention to detail", "fast paced environment")
- Nice-to-haves (anything prefixed with "bonus", "plus", "preferred", "nice to have")
- Vague seniority terms ("senior", "experienced") unless paired with years

Output ONLY valid JSON, no prose or markdown fences:
{{"must_have": ["lowercase", "short", "keywords"], "nice_to_have": ["separate", "list"]}}

Keep keywords SHORT (1-3 words each). Lowercase. No duplicates. No explanations."""


def parse_extraction_response(text: str) -> tuple[list[str], list[str]]:
    cleaned = text.strip()
    # Strip markdown fences if present
    if cleaned.startswith("```"):
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace != -1 and last_brace != -1:
            cleaned = cleaned[first_brace : last_brace + 1]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse extraction response: {e}\nResponse: {cleaned[:500]}"
        ) from e
    must_have = data.get("must_have", [])
    nice_to_have = data.get("nice_to_have", [])
    if not isinstance(must_have, list) or not isinstance(nice_to_have, list):
        raise ValueError(f"Expected lists for must_have/nice_to_have, got: {type(must_have)}")
    return must_have, nice_to_have


class KeywordExtractor:
    def __init__(self, client, model: str, cost_tracker: CostTracker):
        self._client = client
        self._model = model
        self._cost_tracker = cost_tracker

    async def extract(self, job: Job) -> JdKeywords:
        prompt = build_extraction_prompt(job)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        usage = response.usage
        self._cost_tracker.record(
            command="score",
            operation="keyword_extraction",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            job_id=job.id,
        )
        must_have, nice_to_have = parse_extraction_response(text)
        desc_hash = hashlib.sha256(job.description.encode("utf-8")).hexdigest()
        return JdKeywords(
            job_id=job.id,
            must_have=must_have,
            nice_to_have=nice_to_have,
            extracted_at=datetime.now(UTC),
            job_description_hash=desc_hash,
        )

    async def extract_batch(
        self, jobs: list[Job], semaphore: asyncio.Semaphore
    ) -> list[JdKeywords]:
        async def _extract_with_sem(job: Job) -> JdKeywords:
            async with semaphore:
                return await self.extract(job)

        return list(await asyncio.gather(*[_extract_with_sem(j) for j in jobs]))
