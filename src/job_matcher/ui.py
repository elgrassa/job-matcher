"""Rich table and panel rendering for job-matcher CLI output."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from job_matcher.models import Application, ApplicationStatus, Job, MatchScore, ScrapeRun
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
    sources: dict[str, str],
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
    table.add_column("URL", width=40, no_wrap=True)
    table.add_column("Status", width=10)

    for i, s in enumerate(sorted_scores, 1):
        job = jobs.get(s.job_id)
        title = job.title if job else s.job_id[:12]
        company = job.company if job else "?"
        url = sources.get(s.job_id, "")

        # Grey out if already applied with a different CV
        applied_cv = applied_cvs.get(s.job_id)
        if applied_cv and applied_cv != s.cv_id:
            style = "dim"
            status = f"[dim]applied:{applied_cv}[/dim]"
        elif applied_cv == s.cv_id:
            style = "green"
            status = "[green]applied[/green]"
        elif s.hard_filter_triggered:
            style = "red"
            status = f"[red]{s.hard_filter_triggered[:10]}[/red]"
        else:
            style = ""
            status = ""

        if s.final_score >= 0.7:
            final_color = "green"
        elif s.final_score >= 0.5:
            final_color = "yellow"
        else:
            final_color = "red"

        # Truncate URL for display
        url_display = url[:40] if url else ""

        table.add_row(
            str(i),
            f"[{final_color}]{s.final_score:.2f}[/{final_color}]",
            f"{s.keyword_score:.2f}",
            f"{s.semantic_score:.2f}",
            s.cv_id,
            Text(title, style=style, overflow="ellipsis"),
            Text(company, style=style, overflow="ellipsis"),
            Text(url_display, style="dim", overflow="ellipsis"),
            status,
        )

    console.print(table)


def render_filter_summary(scores: list[MatchScore]) -> None:
    """Print aggregate hard filter stats below rank table."""
    filtered = [s for s in scores if s.hard_filter_triggered]
    if not filtered:
        return
    counts: dict[str, int] = {}
    for s in filtered:
        reason = s.hard_filter_triggered or "unknown"
        base = _normalize_filter_reason(reason)
        counts[base] = counts.get(base, 0) + 1
    parts = [f"{count} {reason}" for reason, count in sorted(counts.items(), key=lambda x: -x[1])]
    console.print(f"\n[dim]Filtered: {len(filtered)} ({', '.join(parts)})[/dim]")


def _normalize_filter_reason(reason: str) -> str:
    """Strip dynamic suffixes from filter reasons for grouping.
    e.g. 'rate_below_floor_250eur_day' -> 'rate_below_floor'
         'onsite_in_berlin' -> 'onsite_incompatible'
    """
    if reason.startswith("rate_below_floor"):
        return "rate_below_floor"
    if reason.startswith("onsite_in_"):
        return "onsite_incompatible"
    return reason


def render_job_detail(
    job: Job,
    scores: list[MatchScore],
    applications: list[Application],
    url: str | None = None,
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
    if url:
        info.add_row("URL", url)

    console.print(Panel(info, title=f"Job: {job.id}", border_style="blue"))

    if scores:
        score_table = Table(title="CV Scores")
        score_table.add_column("CV")
        score_table.add_column("Final", justify="center")
        score_table.add_column("Keyword", justify="center")
        score_table.add_column("Semantic", justify="center")
        score_table.add_column("Matched", width=25)
        score_table.add_column("Missing", width=25)
        score_table.add_column("Green Flags")
        score_table.add_column("Red Flags")
        for s in sorted(scores, key=lambda x: x.final_score, reverse=True):
            matched_kw = ", ".join(s.keywords_matched[:5])
            missing_kw = ", ".join(s.keywords_missing[:5])
            if len(s.keywords_matched) > 5:
                matched_kw += "..."
            if len(s.keywords_missing) > 5:
                missing_kw += "..."
            score_table.add_row(
                s.cv_id,
                f"{s.final_score:.2f}",
                f"{s.keyword_score:.2f}",
                f"{s.semantic_score:.2f}",
                Text(matched_kw, style="green"),
                Text(missing_kw, style="red"),
                ", ".join(s.green_flags[:3]),
                ", ".join(s.red_flags[:3]),
            )
        console.print(score_table)

    if applications:
        app_table = Table(title="Applications")
        app_table.add_column("CV")
        app_table.add_column("Status")
        app_table.add_column("Applied At")
        app_table.add_column("Notes")
        for a in applications:
            app_table.add_row(
                a.cv_id,
                a.status.value,
                a.applied_at.strftime("%Y-%m-%d") if a.applied_at else "N/A",
                a.notes[:50] if a.notes else "",
            )
        console.print(app_table)


def render_analytics(scores: list[MatchScore], applications: list[Application]) -> None:
    """Render per-CV analytics dashboard."""
    by_cv: dict[str, list[MatchScore]] = {}
    for s in scores:
        by_cv.setdefault(s.cv_id, []).append(s)

    apps_by_cv: dict[str, list[Application]] = {}
    for a in applications:
        apps_by_cv.setdefault(a.cv_id, []).append(a)

    table = Table(title="Per-CV Analytics")
    table.add_column("CV ID", width=22)
    table.add_column("Avg Score", justify="center")
    table.add_column("Scored", justify="center")
    table.add_column("Filtered", justify="center")
    table.add_column("Applied", justify="center")
    table.add_column("Responses", justify="center")
    table.add_column("Rate", justify="center")

    for cv_id in sorted(by_cv.keys()):
        cv_scores = by_cv[cv_id]
        active = [s for s in cv_scores if not s.hard_filter_triggered]
        filtered = len(cv_scores) - len(active)
        avg = sum(s.final_score for s in active) / len(active) if active else 0.0

        cv_apps = apps_by_cv.get(cv_id, [])
        applied = len([a for a in cv_apps if a.status != ApplicationStatus.SAVED])
        responded = len([
            a for a in cv_apps
            if a.status in (
                ApplicationStatus.SCREENING, ApplicationStatus.INTERVIEW,
                ApplicationStatus.OFFER, ApplicationStatus.REJECTED,
            )
        ])
        rate = f"{responded / applied * 100:.0f}%" if applied > 0 else "N/A"

        table.add_row(
            cv_id, f"{avg:.2f}", str(len(active)), str(filtered),
            str(applied), str(responded), rate,
        )

    console.print(table)

    if not by_cv:
        console.print("[dim]No scores found. Run 'score' first.[/dim]")


def render_apply_warnings(warnings: list[ApplyWarning]) -> None:
    """Print warnings when a user picks a suboptimal CV."""
    if not warnings:
        return
    for w in warnings:
        console.print(
            f"  [yellow]Warning:[/yellow] {w.better_cv_id} scores "
            f"+{w.delta:.2f} higher ({w.reason})"
        )


def render_scrape_summary(run: ScrapeRun) -> None:
    """Print scrape result summary with dedup stats."""
    source = "[dim](cached)[/dim]" if run.cache_hit else "[green](fresh)[/green]"
    dedup = ""
    if run.raw_count > 0 and run.raw_count != run.unique_count:
        dedup = f" [dim]({run.raw_count} raw -> {run.unique_count} unique)[/dim]"
    count = run.unique_count if run.unique_count > 0 else run.jobs_fetched
    console.print(f"  {run.platform}: {count} jobs {source}{dedup}")


def render_error(msg: str) -> None:
    console.print(f"[red]Error:[/red] {msg}")


def render_success(msg: str) -> None:
    console.print(f"[green]{msg}[/green]")
