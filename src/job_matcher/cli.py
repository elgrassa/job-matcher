"""Typer CLI application."""

from typing import Annotated

import typer

from job_matcher import ui

app = typer.Typer(name="job-matcher", no_args_is_help=True)


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
            ui.render_scrape_summary(run.platform, run.jobs_fetched, run.cache_hit)
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
) -> None:
    """Show top-ranked job/CV matches."""
    from job_matcher.storage import jobs_store, scores_store
    from job_matcher.tracker import get_applied_cv

    all_scores = scores_store.all()
    all_jobs = {j.id: j for j in jobs_store.all()}
    applied_cvs = {
        job_id: get_applied_cv(job_id) for job_id in {s.job_id for s in all_scores}
    }
    ui.render_scores_table(all_scores, all_jobs, applied_cvs, top_n=top)


@app.command()
def show(
    job_id: Annotated[str, typer.Argument(help="Job ID (16-char hex)")],
) -> None:
    """Show detailed scores for a specific job."""
    from job_matcher.storage import jobs_store, scores_store
    from job_matcher.tracker import get_applications

    job = jobs_store.find_one(lambda j: j.id == job_id)
    if not job:
        ui.render_error(f"Job {job_id} not found")
        raise typer.Exit(1)

    scores = scores_store.find(lambda s: s.job_id == job_id)
    apps = get_applications(job_id)
    ui.render_job_detail(job, scores, apps)


@app.command()
def apply(
    job_id: Annotated[str, typer.Argument(help="Job ID")],
    cv_id: Annotated[str, typer.Argument(help="CV ID to apply with")],
    notes: Annotated[str, typer.Option("--notes", help="Application notes")] = "",
) -> None:
    """Mark a job as applied with a specific CV."""
    from job_matcher.config import load_scoring_config
    from job_matcher.tracker import apply_to_job, check_apply_warnings

    config = load_scoring_config()
    warnings = check_apply_warnings(job_id, cv_id, config.warning)
    ui.render_apply_warnings(warnings)

    if warnings:
        confirm = typer.confirm("Apply anyway?")
        if not confirm:
            raise typer.Abort()

    app = apply_to_job(job_id, cv_id, notes)
    ui.render_success(f"Applied to {job_id} with {cv_id} (app #{app.id})")


@app.command()
def status(
    job_id: Annotated[str, typer.Argument(help="Job ID")],
    cv_id: Annotated[str, typer.Argument(help="CV ID")],
    new_status: Annotated[str, typer.Argument(help="New status")],
    notes: Annotated[str, typer.Option("--notes", help="Status notes")] = "",
) -> None:
    """Update application status (screening, interview, offer, rejected, etc.)."""
    from job_matcher.models import ApplicationStatus
    from job_matcher.tracker import update_status

    try:
        status_enum = ApplicationStatus(new_status)
    except ValueError:
        valid = ", ".join(s.value for s in ApplicationStatus)
        ui.render_error(f"Invalid status '{new_status}'. Valid: {valid}")
        raise typer.Exit(1) from None

    app = update_status(job_id, cv_id, status_enum, notes)
    if app is None:
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
