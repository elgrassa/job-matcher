"""CSV export for ranked scores."""

import csv
from pathlib import Path

from job_matcher.models import Job, MatchScore


def export_rank_csv(
    path: Path,
    scores: list[MatchScore],
    jobs: dict[str, Job],
    sources: dict[str, str],
    applied_cvs: dict[str, str | None],
) -> int:
    """Write ranked scores to CSV. Returns row count."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Rank", "Score", "KW", "Sem", "CV", "Title", "Company",
            "Location", "Salary", "URL", "Status", "Job ID",
        ])
        for i, score in enumerate(scores, 1):
            job = jobs.get(score.job_id)
            url = sources.get(score.job_id, "")
            applied_cv = applied_cvs.get(score.job_id)

            if score.hard_filter_triggered:
                status = score.hard_filter_triggered
            elif applied_cv == score.cv_id:
                status = "applied"
            elif applied_cv:
                status = f"applied:{applied_cv}"
            else:
                status = ""

            salary = ""
            if job and job.salary_min is not None:
                salary = str(int(job.salary_min))
                if job.salary_max is not None:
                    salary += f"-{int(job.salary_max)}"
                if job.salary_currency:
                    salary += f" {job.salary_currency}"
                if job.salary_period:
                    salary += f"/{job.salary_period}"

            writer.writerow([
                i,
                f"{score.final_score:.2f}",
                f"{score.keyword_score:.2f}",
                f"{score.semantic_score:.2f}",
                score.cv_id,
                job.title if job else "",
                job.company if job else "",
                job.location if job else "",
                salary,
                url,
                status,
                score.job_id,
            ])
    return len(scores)
