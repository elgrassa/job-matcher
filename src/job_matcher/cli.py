"""Typer CLI application."""

from pathlib import Path
from typing import Annotated

import typer

from job_matcher import ui

app = typer.Typer(name="job-matcher", no_args_is_help=True)


@app.callback()
def main(
    profile: Annotated[
        str,
        typer.Option("--profile", "-P", help="User profile (default: 'default')"),
    ] = "default",
) -> None:
    """Job search automation: scrape, score, rank, apply."""
    from job_matcher.profile import migrate_flat_to_profiles, set_profile

    migrate_flat_to_profiles()
    set_profile(profile)


@app.command()
def scrape(
    platform: Annotated[
        list[str] | None,
        typer.Option("--platform", "-p", help="Platform(s) to scrape (default: all enabled)"),
    ] = None,
    max_results: Annotated[
        int | None,
        typer.Option("--max-results", "-n", help="Max results per platform"),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Skip local cache, force fresh scrape"),
    ] = False,
) -> None:
    """Scrape job listings from enabled platforms."""
    from job_matcher.main import run_scrape

    try:
        runs = run_scrape(
            platforms=platform,
            max_results=max_results,
            use_cache=not no_cache,
        )
        for run in runs:
            ui.render_scrape_summary(run)
        ui.render_success(f"Scraped {sum(r.jobs_fetched for r in runs)} total jobs")
    except Exception as e:
        ui.render_error(str(e))
        raise typer.Exit(1) from None


@app.command()
def score(
    only_new: Annotated[
        bool,
        typer.Option("--only-new/--all", help="Only score new/changed pairs"),
    ] = True,
    max_pairs: Annotated[
        int | None,
        typer.Option("--max-pairs", help="Limit total pairs to score"),
    ] = None,
) -> None:
    """Score all jobs against all CVs using keyword + semantic analysis."""
    from job_matcher.main import run_score

    try:
        summary = run_score(only_new=only_new, max_total_pairs=max_pairs)
        ui.render_scoring_summary(summary)
    except Exception as e:
        ui.render_error(str(e))
        raise typer.Exit(1) from None


@app.command()
def rank(
    top: Annotated[
        int,
        typer.Option("--top", "-t", help="Number of top results to show"),
    ] = 20,
    min_score: Annotated[
        float | None,
        typer.Option("--min-score", help="Minimum final score to display"),
    ] = None,
    cv: Annotated[
        str | None,
        typer.Option("--cv", help="Filter by CV ID"),
    ] = None,
    filter_text: Annotated[
        str | None,
        typer.Option("--filter", "-f", help="Filter by title/company text"),
    ] = None,
    export_csv: Annotated[
        str | None,
        typer.Option("--export-csv", help="Export results to CSV file"),
    ] = None,
) -> None:
    """Show top-ranked job/CV matches."""
    from job_matcher.rank_index import save_rank_index
    from job_matcher.storage import jobs_store, scores_store, sources_store
    from job_matcher.tracker import get_applied_cv

    all_scores = scores_store.all()
    all_jobs = {j.id: j for j in jobs_store.all()}
    all_sources: dict[str, str] = {}
    for s in sources_store.all():
        if s.job_id not in all_sources:
            all_sources[s.job_id] = s.url

    applied_cvs = {
        job_id: get_applied_cv(job_id) for job_id in {s.job_id for s in all_scores}
    }

    # Apply filters
    filtered = all_scores
    if min_score is not None:
        filtered = [s for s in filtered if s.final_score >= min_score]
    if cv is not None:
        filtered = [s for s in filtered if s.cv_id == cv]
    if filter_text is not None:
        q = filter_text.lower()
        filtered = [
            s for s in filtered
            if q in (all_jobs.get(s.job_id, _EMPTY_JOB).title.lower())
            or q in (all_jobs.get(s.job_id, _EMPTY_JOB).company.lower())
        ]

    sorted_scores = sorted(filtered, key=lambda s: s.final_score, reverse=True)
    ui.render_scores_table(sorted_scores, all_jobs, all_sources, applied_cvs, top_n=top)
    ui.render_filter_summary(all_scores)

    # Save rank index for short aliases (show 1, apply 2 ...)
    save_rank_index([(s.job_id, s.cv_id) for s in sorted_scores[:top]])

    # CSV export
    if export_csv:
        from job_matcher.export import export_rank_csv

        count = export_rank_csv(
            Path(export_csv), sorted_scores[:top], all_jobs, all_sources, applied_cvs
        )
        ui.render_success(f"Exported {count} rows to {export_csv}")


class _EmptyJob:
    title = ""
    company = ""


_EMPTY_JOB = _EmptyJob()


@app.command()
def show(
    ref: Annotated[str, typer.Argument(help="Job ID (hex) or rank number (1, 2...)")],
) -> None:
    """Show detailed scores for a specific job."""
    from job_matcher.rank_index import resolve_ref
    from job_matcher.storage import jobs_store, scores_store, sources_store
    from job_matcher.tracker import get_applications

    resolved = resolve_ref(ref)
    job_id = resolved[0] if resolved else ref

    job = jobs_store.find_one(lambda j: j.id == job_id)
    if not job:
        ui.render_error(f"Job {job_id} not found")
        raise typer.Exit(1)

    # Find URL from sources
    source = sources_store.find_one(lambda s: s.job_id == job_id)
    url = source.url if source else None

    scores = scores_store.find(lambda s: s.job_id == job_id)
    apps = get_applications(job_id)
    ui.render_job_detail(job, scores, apps, url=url)


@app.command()
def apply(
    ref: Annotated[str, typer.Argument(help="Job ID or rank number")],
    cv_id: Annotated[str, typer.Argument(help="CV ID to apply with")],
    notes: Annotated[str, typer.Option("--notes", help="Application notes")] = "",
) -> None:
    """Mark a job as applied with a specific CV."""
    from job_matcher.config import load_scoring_config
    from job_matcher.rank_index import resolve_ref
    from job_matcher.tracker import apply_to_job, check_apply_warnings

    resolved = resolve_ref(ref)
    job_id = resolved[0] if resolved else ref

    config = load_scoring_config()
    warnings = check_apply_warnings(job_id, cv_id, config.warning)
    ui.render_apply_warnings(warnings)

    if warnings:
        confirm = typer.confirm("Apply anyway?")
        if not confirm:
            raise typer.Abort()

    application = apply_to_job(job_id, cv_id, notes)
    ui.render_success(f"Applied to {job_id} with {cv_id} (app #{application.id})")


@app.command()
def status(
    ref: Annotated[str, typer.Argument(help="Job ID or rank number")],
    cv_id: Annotated[str, typer.Argument(help="CV ID")],
    new_status: Annotated[str, typer.Argument(help="New status")],
    notes: Annotated[str, typer.Option("--notes", help="Status notes")] = "",
) -> None:
    """Update application status (screening, interview, offer, rejected, etc.)."""
    from job_matcher.models import ApplicationStatus
    from job_matcher.rank_index import resolve_ref
    from job_matcher.tracker import update_status

    resolved = resolve_ref(ref)
    job_id = resolved[0] if resolved else ref

    try:
        status_enum = ApplicationStatus(new_status)
    except ValueError:
        valid = ", ".join(s.value for s in ApplicationStatus)
        ui.render_error(f"Invalid status '{new_status}'. Valid: {valid}")
        raise typer.Exit(1) from None

    application = update_status(job_id, cv_id, status_enum, notes)
    if application is None:
        ui.render_error(f"No application found for {job_id} / {cv_id}")
        raise typer.Exit(1)
    ui.render_success(f"Updated {job_id}/{cv_id} -> {new_status}")


@app.command()
def estimate(
    jobs: Annotated[int, typer.Option(help="Number of jobs")] = 100,
    cvs: Annotated[int, typer.Option(help="Number of CVs")] = 7,
) -> None:
    """Estimate LLM cost for a scoring run."""
    from job_matcher.cost_tracker import CostTracker

    tracker = CostTracker()
    est = tracker.estimate_scoring_run(jobs, cvs, include_keyword_extraction=True)
    ui.console.print(f"Estimated: {est.estimated_calls} calls, ${est.estimated_cost_usd:.4f}")


@app.command()
def analytics() -> None:
    """Per-CV effectiveness report: avg scores, filter rates, application stats."""
    from job_matcher.storage import applications_store, scores_store

    all_scores = scores_store.all()
    all_apps = applications_store.all()
    ui.render_analytics(all_scores, all_apps)
