"""Main job-discovery orchestration loop.

Ties the discovery pipeline together and persists every step for full
traceability: discover -> deduplicate -> extract salary -> digest (persisted as
a batch) -> authenticated approval -> apply -> record outcome.

Approvals are gated: ``record_approval_reply`` honors a reply only when its
sender is a configured owner address (``is_authorized_sender``). Application
submission is delegated to injected per-platform agents so orchestration is
testable independently of the live submission endpoints.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, Iterable, Iterator, List, Optional

from loguru import logger

from src.agents.base_agent import (
    Agent,
    ApplicationResult,
    CandidateProfile,
    JobListing,
)
from src.database.schema import get_connection
from src.orchestrator.approval_parser import is_authorized_sender, parse_approvals
from src.orchestrator.deduplicator import JobDeduplicator
from src.orchestrator.digest_generator import generate_digest
from src.orchestrator.discovery import discover_jobs
from src.orchestrator.salary_extractor import extract_salary, meets_floor

SALARY_FLOOR_DEFAULT = 40.0
BATCH_STALE_HOURS = 24
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# ApplicationResult -> jobs.status terminal value.
_JOB_STATUS_BY_RESULT = {
    ApplicationResult.SUCCESS: "submitted",
    ApplicationResult.FAILED: "failed",
    ApplicationResult.MANUAL_REVIEW: "manual_required",
}


@dataclass
class DiscoverySource:
    """One platform to discover from in a batch run."""

    platform: str
    board_token: Optional[str] = None
    company: Optional[str] = None


@dataclass
class DigestResult:
    """Outcome of a discovery run that produced a batch."""

    batch_id: str
    digest: str
    job_count: int


@dataclass
class ApprovalOutcome:
    """Result of processing a user's approval reply."""

    authorized: bool
    approved_positions: List[str] = field(default_factory=list)
    rejected_positions: List[str] = field(default_factory=list)
    reason: Optional[str] = None


@dataclass
class ApplySummary:
    """Tally of submission outcomes for an applied batch."""

    submitted: int = 0
    failed: int = 0
    manual_review: int = 0


class JobOrchestrator:
    """Coordinates discovery, approval, and application for a single user."""

    def __init__(
        self,
        profile: CandidateProfile,
        agents: Dict[str, Agent],
        authorized_senders: Iterable[str],
        user_email: str = "",
        discover: Callable[..., List[JobListing]] = discover_jobs,
        salary_floor: float = SALARY_FLOOR_DEFAULT,
    ):
        self.profile = profile
        self.agents = agents
        self.authorized_senders = list(authorized_senders)
        self.user_email = user_email
        self.discover = discover
        self.salary_floor = salary_floor

    def discover_and_digest(self, sources: List[DiscoverySource]) -> Optional[DigestResult]:
        """Discover across sources, dedupe, persist a batch, and build the digest.

        Returns None when no jobs are found, in which case no batch is created.
        """
        unique_jobs = self._discover_unique(sources)
        if not unique_jobs:
            logger.info("No jobs discovered; no batch created")
            return None

        salaries = {job.id: extract_salary(getattr(job, "description", "") or "") for job in unique_jobs}
        kept = [job for job in unique_jobs if meets_floor(salaries[job.id], self.salary_floor)]

        batch_id = str(uuid.uuid4())
        self._persist_batch(batch_id, kept, salaries)

        digest = generate_digest(
            jobs=kept,
            salaries=salaries,
            salary_floor=self.salary_floor,
            batch_id=batch_id,
        )
        logger.info(f"Created batch {batch_id} with {len(kept)} jobs")
        return DigestResult(batch_id=batch_id, digest=digest, job_count=len(kept))

    def record_approval_reply(
        self,
        batch_id: str,
        sender: str,
        reply_text: str,
        received_at: Optional[datetime] = None,
    ) -> ApprovalOutcome:
        """Validate the sender, then record approvals/rejections for a batch.

        An unauthorized sender is logged and ignored: no approval is recorded and
        nothing is persisted. This is the enforcement point for VULN-1-1.
        """
        if not is_authorized_sender(sender, self.authorized_senders):
            logger.warning(f"Ignoring approval reply from unauthorized sender: {sender}")
            return ApprovalOutcome(authorized=False, reason="unauthorized_sender")

        total_jobs = self._batch_size(batch_id)
        parsed = parse_approvals(reply_text, total_jobs=total_jobs, return_all=True)
        self._apply_approval_statuses(batch_id, parsed["approved"], parsed["rejected"])
        self._log_approval(batch_id, sender, reply_text, parsed, received_at)

        logger.info(f"Recorded approvals for batch {batch_id}: {parsed['approved']}")
        return ApprovalOutcome(
            authorized=True,
            approved_positions=parsed["approved"],
            rejected_positions=parsed["rejected"],
        )

    def apply_to_batch(self, batch_id: str) -> ApplySummary:
        """Submit every approved job in the batch and record each outcome."""
        approved = self._approved_jobs(batch_id)
        summary = ApplySummary()

        for job in approved:
            result = self._apply_one(job)
            if result is ApplicationResult.SUCCESS:
                summary.submitted += 1
            elif result is ApplicationResult.MANUAL_REVIEW:
                summary.manual_review += 1
            else:
                summary.failed += 1

        self._mark_batch_approved(batch_id)
        logger.info(f"Applied batch {batch_id}: {summary}")
        return summary

    def send_daily_reminder(self, now: Optional[datetime] = None) -> List[str]:
        """Return IDs of pending batches older than the stale threshold."""
        cutoff = (now or datetime.now()) - timedelta(hours=BATCH_STALE_HOURS)
        cutoff_str = cutoff.strftime(TIMESTAMP_FORMAT)

        with _transaction() as conn:
            rows = conn.execute(
                "SELECT id FROM job_batches "
                "WHERE status = 'pending' AND deleted_at IS NULL AND discovered_at < ?",
                (cutoff_str,),
            ).fetchall()
        stale_ids = [row[0] for row in rows]
        logger.info(f"Daily reminder: {len(stale_ids)} stale pending batch(es)")
        return stale_ids

    def _discover_unique(self, sources: List[DiscoverySource]) -> List[JobListing]:
        """Discover from every source and drop cross-platform duplicates."""
        discovered: List[JobListing] = []
        for source in sources:
            discovered.extend(
                self.discover(
                    platform=source.platform,
                    board_token=source.board_token,
                    company=source.company,
                )
            )
        return JobDeduplicator().filter_non_duplicates(discovered)

    def _persist_batch(
        self,
        batch_id: str,
        jobs: List[JobListing],
        salaries: Dict[str, Optional[float]],
    ) -> None:
        """Insert the batch, its jobs, and discovery records in FK-safe order."""
        now = _now_str()
        with _transaction() as conn:
            conn.execute(
                "INSERT INTO job_batches (id, discovered_at, status, batch_size, user_email) "
                "VALUES (?, ?, 'pending', ?, ?)",
                (batch_id, now, len(jobs), self.user_email),
            )
            for position, job in enumerate(jobs, start=1):
                conn.execute(
                    "INSERT OR IGNORE INTO jobs (id, title, company, platform, url) VALUES (?, ?, ?, ?, ?)",
                    (job.id, job.title, job.company, job.platform, job.url),
                )
                conn.execute(
                    "INSERT INTO batch_jobs (id, batch_id, job_id, position) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), batch_id, job.id, position),
                )
                conn.execute(
                    "INSERT INTO job_discoveries "
                    "(id, platform, job_id, title, company, salary_hourly, link, batch_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        job.platform,
                        job.id,
                        job.title,
                        job.company,
                        salaries.get(job.id),
                        job.url,
                        batch_id,
                    ),
                )

    def _batch_size(self, batch_id: str) -> int:
        """Return the recorded job count for a batch (0 if unknown)."""
        with _transaction() as conn:
            row = conn.execute(
                "SELECT batch_size FROM job_batches WHERE id = ?", (batch_id,)
            ).fetchone()
        return row[0] if row and row[0] is not None else 0

    def _apply_approval_statuses(
        self, batch_id: str, approved: List[str], rejected: List[str]
    ) -> None:
        """Set approval status on batch_jobs by digest position."""
        now = _now_str()
        with _transaction() as conn:
            for position in approved:
                conn.execute(
                    "UPDATE batch_jobs SET user_approval_status = 'approved', approved_at = ? "
                    "WHERE batch_id = ? AND position = ?",
                    (now, batch_id, int(position)),
                )
            for position in rejected:
                conn.execute(
                    "UPDATE batch_jobs SET user_approval_status = 'rejected' "
                    "WHERE batch_id = ? AND position = ?",
                    (batch_id, int(position)),
                )

    def _log_approval(
        self,
        batch_id: str,
        sender: str,
        reply_text: str,
        parsed: Dict,
        received_at: Optional[datetime],
    ) -> None:
        """Append an audit record of the approval reply."""
        received = (received_at or datetime.now()).strftime(TIMESTAMP_FORMAT)
        with _transaction() as conn:
            conn.execute(
                "INSERT INTO approval_log "
                "(id, batch_id, user_email, approval_text, parsed_approvals, received_at, processed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    batch_id,
                    sender,
                    reply_text,
                    json.dumps(parsed),
                    received,
                    _now_str(),
                ),
            )

    def _approved_jobs(self, batch_id: str) -> List[JobListing]:
        """Load approved jobs for a batch, ordered by digest position."""
        with _transaction() as conn:
            rows = conn.execute(
                "SELECT j.id, j.title, j.company, j.url, j.platform "
                "FROM batch_jobs b JOIN jobs j ON j.id = b.job_id "
                "WHERE b.batch_id = ? AND b.user_approval_status = 'approved' "
                "ORDER BY b.position",
                (batch_id,),
            ).fetchall()
        return [
            JobListing(id=r[0], title=r[1], company=r[2], url=r[3], platform=r[4])
            for r in rows
        ]

    def _apply_one(self, job: JobListing) -> ApplicationResult:
        """Submit one job through its platform agent and record the outcome.

        A raising agent is contained here so one failure cannot abort the batch
        and lose the remaining approved jobs: the failure is logged and recorded
        as a FAILED application, preserving traceability.
        """
        agent = self.agents.get(job.platform)
        if agent is None:
            logger.error(f"No agent configured for platform {job.platform}; recording failure")
            self._record_application(job, ApplicationResult.FAILED, None, "no_agent")
            return ApplicationResult.FAILED

        try:
            result = agent.submit_application(job, self.profile)
        except Exception as exc:  # boundary: an agent must never abort the batch
            logger.error(f"Agent for {job.platform} raised on job {job.id}: {exc}")
            self._record_application(job, ApplicationResult.FAILED, None, str(exc))
            return ApplicationResult.FAILED

        self._record_application(
            job, result.status, result.application_id, result.error_message
        )
        return result.status

    def _record_application(
        self,
        job: JobListing,
        status: ApplicationResult,
        application_id: Optional[str],
        error_message: Optional[str],
    ) -> None:
        """Persist an application row, its status history, and the job's status."""
        app_id = application_id or str(uuid.uuid4())
        now = _now_str()
        with _transaction() as conn:
            conn.execute(
                "INSERT INTO applications "
                "(id, job_id, submitted_at, result, error_log, current_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (app_id, job.id, now, status.value, error_message, status.value),
            )
            conn.execute(
                "INSERT INTO status_history "
                "(id, application_id, old_status, new_status, changed_by, automation_type) "
                "VALUES (?, ?, 'pending', ?, 'orchestrator', ?)",
                (str(uuid.uuid4()), app_id, status.value, job.platform),
            )
            conn.execute(
                "UPDATE jobs SET status = ? WHERE id = ?",
                (_JOB_STATUS_BY_RESULT[status], job.id),
            )

    def _mark_batch_approved(self, batch_id: str) -> None:
        """Mark a batch as approved once its applications have been processed."""
        with _transaction() as conn:
            conn.execute(
                "UPDATE job_batches SET status = 'approved', approved_at = ? WHERE id = ?",
                (_now_str(), batch_id),
            )


@contextmanager
def _transaction() -> Iterator:
    """Yield a FK-enforcing connection, committing on success and always closing."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now_str(dt: Optional[datetime] = None) -> str:
    """Format a timestamp consistently for storage and comparison."""
    return (dt or datetime.now()).strftime(TIMESTAMP_FORMAT)
