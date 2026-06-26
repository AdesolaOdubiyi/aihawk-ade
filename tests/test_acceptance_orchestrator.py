"""Phase 4: End-to-end acceptance tests for the JobOrchestrator main loop.

These exercise the full user workflow against the real SQLite schema:
discover -> dedupe -> digest -> (authenticated) approve -> apply -> persist,
plus the daily reminder for stale pending batches.

Application submission is driven through injected agents (FakeAgent) so the
orchestration and persistence are validated independently of the live
Greenhouse/Lever submission endpoints (deferred to Gate 1/2).
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from src.agents.base_agent import (
    Agent,
    ApplicationResult,
    CandidateProfile,
    JobListing,
    SubmissionResult,
)
from src.database import schema
from src.orchestrator.orchestrator import DiscoverySource, JobOrchestrator

OWNER_EMAIL = "jane@example.com"
GREENHOUSE_SOURCE = DiscoverySource(platform="greenhouse", board_token="acme-board")
LEVER_SOURCE = DiscoverySource(platform="lever", company="Acme")
ALL_SOURCES = [GREENHOUSE_SOURCE, LEVER_SOURCE]


class FakeAgent(Agent):
    """Records submissions and returns a configurable result."""

    def __init__(self, platform: str, result_status: ApplicationResult = ApplicationResult.SUCCESS):
        super().__init__(f"Fake-{platform}")
        self.result_status = result_status
        self.submitted_job_ids: list = []

    def submit_application(self, job: JobListing, profile: CandidateProfile) -> SubmissionResult:
        self.submitted_job_ids.append(job.id)
        return SubmissionResult(
            status=self.result_status,
            application_id=f"app-{job.id}",
            error_message=None if self.result_status is ApplicationResult.SUCCESS else "stub failure",
            fields_filled={"name": profile.full_name},
        )


def _sample_jobs() -> list:
    """gh-1 and lv-1 are the same posting (dedupe target); gh-2 is distinct."""
    return [
        JobListing(id="gh-1", title="Software Engineer", company="Acme", url="https://gh/1", platform="greenhouse"),
        JobListing(id="gh-2", title="Data Analyst", company="Acme", url="https://gh/2", platform="greenhouse"),
        JobListing(id="lv-1", title="Software Engineer", company="Acme", url="https://lv/1", platform="lever"),
    ]


def _discover_from_sample(platform, board_token=None, company=None, filters=None):
    return [job for job in _sample_jobs() if job.platform == platform]


def _discover_nothing(platform, board_token=None, company=None, filters=None):
    return []


@pytest.fixture
def profile() -> CandidateProfile:
    return CandidateProfile(
        full_name="Jane Doe",
        email=OWNER_EMAIL,
        phone="+1-555-0100",
        resume_path="/resume.pdf",
    )


@pytest.fixture
def agents() -> dict:
    return {
        "greenhouse": FakeAgent("greenhouse"),
        "lever": FakeAgent("lever"),
    }


@pytest.fixture
def orchestrator(profile, agents) -> JobOrchestrator:
    return JobOrchestrator(
        profile=profile,
        agents=agents,
        authorized_senders=[OWNER_EMAIL],
        user_email=OWNER_EMAIL,
        discover=_discover_from_sample,
        salary_floor=40.0,
    )


def _count(table: str, where: str = "") -> int:
    conn = sqlite3.connect(schema.DB_PATH)
    try:
        clause = f" WHERE {where}" if where else ""
        return conn.execute(f"SELECT COUNT(*) FROM {table}{clause}").fetchone()[0]
    finally:
        conn.close()


class TestDiscoverAndDigest:
    def test_creates_batch_dedupes_and_returns_digest(self, temp_db, orchestrator):
        result = orchestrator.discover_and_digest(ALL_SOURCES)

        assert result is not None
        assert result.job_count == 2  # lv-1 deduped against gh-1
        assert "Software Engineer" in result.digest
        assert "Data Analyst" in result.digest
        assert "APPROVE" in result.digest

        assert _count("job_batches", f"id = '{result.batch_id}'") == 1
        assert _count("batch_jobs", f"batch_id = '{result.batch_id}'") == 2
        assert _count("job_discoveries", f"batch_id = '{result.batch_id}'") == 2
        # Both surviving jobs are persisted in the jobs table (FK target).
        assert _count("jobs", "id IN ('gh-1', 'gh-2')") == 2

    def test_positions_are_contiguous_starting_at_one(self, temp_db, orchestrator):
        result = orchestrator.discover_and_digest(ALL_SOURCES)

        conn = sqlite3.connect(schema.DB_PATH)
        try:
            positions = [
                row[0]
                for row in conn.execute(
                    "SELECT position FROM batch_jobs WHERE batch_id = ? ORDER BY position",
                    (result.batch_id,),
                ).fetchall()
            ]
        finally:
            conn.close()
        assert positions == [1, 2]

    def test_empty_discovery_creates_no_batch(self, temp_db, profile, agents):
        orchestrator = JobOrchestrator(
            profile=profile,
            agents=agents,
            authorized_senders=[OWNER_EMAIL],
            user_email=OWNER_EMAIL,
            discover=_discover_nothing,
        )

        result = orchestrator.discover_and_digest(ALL_SOURCES)

        assert result is None
        assert _count("job_batches") == 0


class TestApprovalAuthentication:
    def test_unauthorized_sender_is_rejected(self, temp_db, orchestrator):
        batch = orchestrator.discover_and_digest(ALL_SOURCES)

        outcome = orchestrator.record_approval_reply(
            batch_id=batch.batch_id,
            sender="attacker@evil.com",
            reply_text="APPROVE all",
        )

        assert outcome.authorized is False
        assert outcome.approved_positions == []
        assert _count("batch_jobs", f"batch_id = '{batch.batch_id}' AND user_approval_status = 'approved'") == 0
        assert _count("approval_log", f"batch_id = '{batch.batch_id}'") == 0

    def test_authorized_sender_marks_selected_jobs_approved(self, temp_db, orchestrator):
        batch = orchestrator.discover_and_digest(ALL_SOURCES)

        outcome = orchestrator.record_approval_reply(
            batch_id=batch.batch_id,
            sender=f"Jane Doe <{OWNER_EMAIL}>",
            reply_text="APPROVE: 1",
        )

        assert outcome.authorized is True
        assert outcome.approved_positions == ["1"]
        assert _count("batch_jobs", f"batch_id = '{batch.batch_id}' AND user_approval_status = 'approved'") == 1
        assert _count("batch_jobs", f"batch_id = '{batch.batch_id}' AND user_approval_status = 'pending'") == 1
        assert _count("approval_log", f"batch_id = '{batch.batch_id}'") == 1


class TestApplyToBatch:
    def test_applies_only_approved_jobs_and_records_results(self, temp_db, orchestrator, agents):
        batch = orchestrator.discover_and_digest(ALL_SOURCES)
        orchestrator.record_approval_reply(batch.batch_id, OWNER_EMAIL, "APPROVE: 1")

        summary = orchestrator.apply_to_batch(batch.batch_id)

        assert summary.submitted == 1
        assert agents["greenhouse"].submitted_job_ids == ["gh-1"]
        assert agents["lever"].submitted_job_ids == []  # gh-2 only, lever job was deduped
        assert _count("applications", "job_id = 'gh-1' AND result = 'success'") == 1
        assert _count("status_history") >= 1

    def test_failed_submission_is_recorded_not_lost(self, temp_db, profile):
        agents = {
            "greenhouse": FakeAgent("greenhouse", ApplicationResult.FAILED),
            "lever": FakeAgent("lever"),
        }
        orchestrator = JobOrchestrator(
            profile=profile,
            agents=agents,
            authorized_senders=[OWNER_EMAIL],
            user_email=OWNER_EMAIL,
            discover=_discover_from_sample,
        )
        batch = orchestrator.discover_and_digest(ALL_SOURCES)
        orchestrator.record_approval_reply(batch.batch_id, OWNER_EMAIL, "APPROVE all")

        summary = orchestrator.apply_to_batch(batch.batch_id)

        assert summary.failed >= 1
        # Traceability: every approved job produced an application row regardless of outcome.
        assert _count("applications") == 2

    def test_raising_agent_does_not_abort_batch(self, temp_db, profile):
        class RaisingAgent(FakeAgent):
            def submit_application(self, job, candidate_profile=None):
                raise RuntimeError("network exploded")

        agents = {
            "greenhouse": RaisingAgent("greenhouse"),
            "lever": FakeAgent("lever"),
        }
        orchestrator = JobOrchestrator(
            profile=profile,
            agents=agents,
            authorized_senders=[OWNER_EMAIL],
            user_email=OWNER_EMAIL,
            discover=_discover_from_sample,
        )
        batch = orchestrator.discover_and_digest(ALL_SOURCES)
        orchestrator.record_approval_reply(batch.batch_id, OWNER_EMAIL, "APPROVE all")

        summary = orchestrator.apply_to_batch(batch.batch_id)

        # Both approved jobs are greenhouse-tier and raise, but neither is lost.
        assert summary.failed == 2
        assert _count("applications", "result = 'failed'") == 2


class TestDailyReminder:
    def test_returns_stale_pending_batches_only(self, temp_db, orchestrator):
        fresh = orchestrator.discover_and_digest(ALL_SOURCES)

        stale_id = "stale-batch"
        stale_time = (datetime.now() - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(schema.DB_PATH)
        try:
            conn.execute(
                "INSERT INTO job_batches (id, discovered_at, status, batch_size, user_email) "
                "VALUES (?, ?, 'pending', 1, ?)",
                (stale_id, stale_time, OWNER_EMAIL),
            )
            conn.commit()
        finally:
            conn.close()

        stale = orchestrator.send_daily_reminder()

        assert stale_id in stale
        assert fresh.batch_id not in stale


class TestEndToEndWorkflow:
    def test_full_discover_approve_apply_flow(self, temp_db, orchestrator, agents):
        batch = orchestrator.discover_and_digest(ALL_SOURCES)
        assert batch.job_count == 2

        outcome = orchestrator.record_approval_reply(batch.batch_id, OWNER_EMAIL, "APPROVE all")
        assert outcome.authorized is True
        assert sorted(outcome.approved_positions) == ["1", "2"]

        summary = orchestrator.apply_to_batch(batch.batch_id)
        assert summary.submitted == 2
        assert _count("applications", f"result = 'success'") == 2
        # Batch is marked approved once processed.
        assert _count("job_batches", f"id = '{batch.batch_id}' AND status = 'approved'") == 1
