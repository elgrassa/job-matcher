"""Rich table and panel rendering for job-matcher CLI output."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from job_matcher.models import Application, Job, MatchScore
from job_matcher.scoring.pipeline import ScoringRunSummary
from job_matcher.tracker import ApplyWarning

console = Console()


def render_scoring_summary(summary: ScoringRunSummary) -> None:
    """Print a summary panel after a scoring run."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Jobs processed", str(summary.jobs_processed))
    table.add_row("Pairs scored", str(summary.pairs_scored))
    table.add_row("Skipped (fresh)", str(summary.pairs_skipped_fresh))
    table.add_row("Skipped (filtered)", str(summary.pairs_skipped_filtered))
    table.add_row("Total cost", f"${summary.total_cost_usd:.4f}")
    table.add_row("Duration", f"{summary.duration_seconds:.1f}s")
    console.print(Panel(table, title="Scoring Run", border_style="green"))


def render_scores_table(
    scores: list[MatchScore],
    jobs: dict[str, Job],
    applied_cvs: dict[str, str | None],
    top_n: int = 20,
) -> None:
    """Render a ranked table of top-scoring job/CV pairs."""
    sorted_scores = sorted(scores, key=lambda s: s.final_score, reverse=True)[:top_n]
    table = Table(title=f"Top {top_n} Matches", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", justify="center", width=6)
    table.add_column("KW", justify="center", width=5)
    table.add_column("Sem", justify="center", width=5)
    table.add_column("CV", width=15)
    table.add_column("Title", width=30)
    table.add_column("Company", width=20)
    table.add_column("Status", width=10)

    for i, score in enumerate(sorted_scores, 1):
        job = jobs.get(score.job_id)
        title = job.title if job else score.job_id[:12]
        company = job.company if job else "?"

        # Grey out if already applied with a different CV
        applied_cv = applied_cvs.get(score.job_id)
        if applied_cv and applied_cv != score.cv_id:
            style = "dim"
            status = f"[dim]applied:{applied_cv}[/dim]"
        elif applied_cv == score.cv_id:
            style = "green"
            status = "[green]applied[/green]"
        elif score.hard_filter_triggered:
            style = "red"
            status = f"[red]{score.hard_filter_triggered[:10]}[/red]"
        else:
            style = ""
            status = ""

        if score.final_score >= 0.7:
            final_color = "green"
        elif score.final_score >= 0.5:
            final_color = "yellow"
        else:
            final_color = "red"
        table.add_row(
            str(i),
            f"[{final_color}]{score.final_score:.2f}[/{final_color}]",
            f"{score.keyword_score:.2f}",
            f"{score.semantic_score:.2f}",
            score.cv_id,
            Text(title, style=style, overflow="ellipsis"),
            Text(company, style=style, overflow="ellipsis"),
            status,
        )

    console.print(table)


def render_job_detail(
    job: Job,
    scores: list[MatchScore],
    applications: list[Application],
) -> None:
    """Render detailed view for a single job with all CV scores."""
    info = Table(show_header=False, box=None, padding=(0, 2))
    info.add_column("Field", style="bold")
    info.add_column("Value")
    info.add_row("Title", job.title)
    info.add_row("Company", job.company)
    info.add_row("Location", job.location or "N/A")
    info.add_row("Remote", job.remote_type)
    info.add_row("Employment", job.employment_type)
    if job.salary_min:
        sal = f"{job.salary_min}"
        if job.salary_max:
            sal += f"-{job.salary_max}"
        if job.salary_currency:
            sal += f" {job.salary_currency}"
        if job.salary_period:
            sal += f"/{job.salary_period}"
        info.add_row("Salary", sal)

    console.print(Panel(info, title=f"Job: {job.id}", border_style="blue"))

    if scores:
        score_table = Table(title="CV Scores")
        score_table.add_column("CV")
        score_table.add_column("Final", justify="center")
        score_table.add_column("Keyword", justify="center")
        score_table.add_column("Semantic", justify="center")
        score_table.add_column("Green Flags")
        score_table.add_column("Red Flags")
        for s in sorted(scores, key=lambda x: x.final_score, reverse=True):
            score_table.add_row(
                s.cv_id,
                f"{s.final_score:.2f}",
                f"{s.keyword_score:.2f}",
                f"{s.semantic_score:.2f}",
                ", ".join(s.green_flags[:3]),
                ", ".join(s.red_flags[:3]),
            )
        console.print(score_table)


def render_apply_warnings(warnings: list[ApplyWarning]) -> None:
    """Print warnings when a user picks a suboptimal CV."""
    if not warnings:
        return
    for w in warnings:
        console.print(
            f"  [yellow]Warning:[/yellow] {w.better_cv_id} scores "
            f"+{w.delta:.2f} higher ({w.reason})"
        )


def render_scrape_summary(platform: str, count: int, cached: bool) -> None:
    """Print scrape result summary."""
    source = "[dim](cached)[/dim]" if cached else "[green](fresh)[/green]"
    console.print(f"  {platform}: {count} jobs {source}")


def render_error(msg: str) -> None:
    console.print(f"[red]Error:[/red] {msg}")


def render_success(msg: str) -> None:
    console.print(f"[green]{msg}[/green]")
