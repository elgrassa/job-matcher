"""Application state tracking and cross-CV grey-out logic.

Manages the lifecycle of job applications: save -> apply -> interview -> offer/reject.
Provides warnings when multiple CVs score well for the same job (pick one before applying).
"""

import logging
from datetime import UTC, datetime

from job_matcher.config import WarningConfig
from job_matcher.models import Application, ApplicationStatus
from job_matcher.storage import applications_store, scores_store

logger = logging.getLogger(__name__)


class ApplyWarning:
    """Warning: another CV scores significantly better for this job."""

    def __init__(
        self,
        job_id: str,
        chosen_cv_id: str,
        better_cv_id: str,
        delta: float,
        reason: str,
    ):
        self.job_id = job_id
        self.chosen_cv_id = chosen_cv_id
        self.better_cv_id = better_cv_id
        self.delta = delta
        self.reason = reason

    def __repr__(self) -> str:
        return (
            f"ApplyWarning({self.reason}: "
            f"{self.better_cv_id} scores +{self.delta:.2f} vs {self.chosen_cv_id})"
        )


def _next_app_id() -> int:
    apps = applications_store.all()
    if not apps:
        return 1
    return max(a.id for a in apps) + 1


def _find_application(job_id: str, cv_id: str) -> Application | None:
    return applications_store.find_one(
        lambda a: a.job_id == job_id and a.cv_id == cv_id
    )


def _app_key(a):
    return a.id


def save_job(job_id: str, cv_id: str, notes: str = "") -> Application:
    """Mark a job as saved (bookmarked) for a specific CV."""
    now = datetime.now(UTC)
    app = Application(
        id=_next_app_id(),
        job_id=job_id,
        cv_id=cv_id,
        status=ApplicationStatus.SAVED,
        saved_at=now,
        applied_at=None,
        last_status_change_at=now,
        notes=notes,
        status_history=[{"status": "saved", "at": now.isoformat()}],
    )
    applications_store.upsert(app, _app_key)
    return app


def apply_to_job(job_id: str, cv_id: str, notes: str = "") -> Application:
    """Mark a job as applied with a specific CV."""
    now = datetime.now(UTC)
    existing = _find_application(job_id, cv_id)
    if existing:
        existing.status = ApplicationStatus.APPLIED
        existing.applied_at = now
        existing.last_status_change_at = now
        existing.status_history.append({"status": "applied", "at": now.isoformat()})
        if notes:
            existing.notes = notes
        applications_store.upsert(existing, _app_key)
        return existing
    app = Application(
        id=_next_app_id(),
        job_id=job_id,
        cv_id=cv_id,
        status=ApplicationStatus.APPLIED,
        saved_at=None,
        applied_at=now,
        last_status_change_at=now,
        notes=notes,
        status_history=[{"status": "applied", "at": now.isoformat()}],
    )
    applications_store.upsert(app, _app_key)
    return app


def update_status(
    job_id: str, cv_id: str, new_status: ApplicationStatus, notes: str = ""
) -> Application | None:
    """Update the status of an existing application."""
    app = _find_application(job_id, cv_id)
    if app is None:
        return None
    now = datetime.now(UTC)
    app.status = new_status
    app.last_status_change_at = now
    app.status_history.append({"status": new_status.value, "at": now.isoformat()})
    if notes:
        app.notes = notes
    applications_store.upsert(app, _app_key)
    return app


def get_applications(job_id: str | None = None) -> list[Application]:
    """Get all applications, optionally filtered by job_id."""
    apps = applications_store.all()
    if job_id:
        return [a for a in apps if a.job_id == job_id]
    return apps


def is_greyed_out(job_id: str) -> bool:
    """True if any CV has an active (non-saved, non-withdrawn) application to this job."""
    return any(
        a.status not in (ApplicationStatus.SAVED, ApplicationStatus.WITHDRAWN)
        for a in get_applications(job_id)
    )


def get_applied_cv(job_id: str) -> str | None:
    """Return the cv_id used for an active application to this job, or None."""
    for app in get_applications(job_id):
        if app.status not in (ApplicationStatus.SAVED, ApplicationStatus.WITHDRAWN):
            return app.cv_id
    return None


def check_apply_warnings(
    job_id: str,
    chosen_cv_id: str,
    config: WarningConfig,
) -> list[ApplyWarning]:
    """Check if another CV scores significantly better for this job."""
    warnings: list[ApplyWarning] = []
    all_scores = scores_store.find(lambda s: s.job_id == job_id)
    chosen_score = next((s for s in all_scores if s.cv_id == chosen_cv_id), None)
    if chosen_score is None:
        return warnings

    for score in all_scores:
        if score.cv_id == chosen_cv_id:
            continue
        final_delta = score.final_score - chosen_score.final_score
        kw_delta = score.keyword_score - chosen_score.keyword_score

        if final_delta >= config.score_delta_threshold:
            warnings.append(ApplyWarning(
                job_id=job_id,
                chosen_cv_id=chosen_cv_id,
                better_cv_id=score.cv_id,
                delta=final_delta,
                reason=f"final_score +{final_delta:.2f}",
            ))
        elif kw_delta >= config.keyword_delta_threshold:
            warnings.append(ApplyWarning(
                job_id=job_id,
                chosen_cv_id=chosen_cv_id,
                better_cv_id=score.cv_id,
                delta=kw_delta,
                reason=f"keyword_score +{kw_delta:.2f}",
            ))

    return sorted(warnings, key=lambda w: w.delta, reverse=True)
