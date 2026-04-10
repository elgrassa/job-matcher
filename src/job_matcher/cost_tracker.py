"""LLM cost tracking and estimates."""

from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from pydantic import BaseModel

from job_matcher.constants import DEFAULT_MODEL, MODEL_PRICING
from job_matcher.models import CostLedgerEntry
from job_matcher.storage import cost_store


class CostEstimate(BaseModel):
    estimated_calls: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float


class CostTracker:
    def __init__(self, model: str = DEFAULT_MODEL):
        self._model = model
        pricing = MODEL_PRICING.get(model)
        if pricing is None:
            raise ValueError(
                f"Unknown model '{model}' — not in MODEL_PRICING. "
                f"Known models: {list(MODEL_PRICING.keys())}"
            )
        self._input_price_per_token = pricing["input"] / 1_000_000
        self._output_price_per_token = pricing["output"] / 1_000_000
        self._next_id = self._compute_next_id()

    def _compute_next_id(self) -> int:
        entries = cost_store.all()
        if not entries:
            return 1
        return int(max(e.id for e in entries)) + 1

    def _compute_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self._input_price_per_token
            + output_tokens * self._output_price_per_token
        )

    def record(
        self,
        command: str,
        operation: str,
        input_tokens: int,
        output_tokens: int,
        job_id: str | None = None,
        cv_id: str | None = None,
    ) -> CostLedgerEntry:
        cost = self._compute_cost(input_tokens, output_tokens)
        entry = CostLedgerEntry(
            id=self._next_id,
            timestamp=datetime.now(UTC),
            command=command,
            operation=cast(
                Literal["keyword_extraction", "semantic_scoring"], operation
            ),
            job_id=job_id,
            cv_id=cv_id,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
        )
        cost_store.upsert(entry, lambda e: e.id)
        self._next_id += 1
        return entry

    def estimate_scoring_run(
        self,
        num_jobs: int,
        num_cvs: int,
        include_keyword_extraction: bool,
    ) -> CostEstimate:
        kw_calls = num_jobs if include_keyword_extraction else 0
        score_calls = num_jobs * num_cvs
        total_calls = kw_calls + score_calls

        kw_input = kw_calls * 1500
        kw_output = kw_calls * 150
        score_input = score_calls * 1500
        score_output = score_calls * 200

        total_input = kw_input + score_input
        total_output = kw_output + score_output
        total_cost = self._compute_cost(total_input, total_output)

        return CostEstimate(
            estimated_calls=total_calls,
            estimated_input_tokens=total_input,
            estimated_output_tokens=total_output,
            estimated_cost_usd=round(total_cost, 4),
        )

    def total_cost_last_7_days(self) -> float:
        cutoff = datetime.now(UTC) - timedelta(days=7)
        return float(sum(e.cost_usd for e in cost_store.all() if e.timestamp >= cutoff))

    def total_cost_this_month(self) -> float:
        now = datetime.now(UTC)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return float(sum(e.cost_usd for e in cost_store.all() if e.timestamp >= month_start))

    def summary_by_operation(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for entry in cost_store.all():
            result[entry.operation] = result.get(entry.operation, 0.0) + entry.cost_usd
        return result
