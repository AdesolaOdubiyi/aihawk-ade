"""SQLite schema definition and connection management.

All connections are created through ``get_connection`` so that
``PRAGMA foreign_keys = ON`` is set every time. SQLite ignores declared foreign
keys unless that pragma is enabled per-connection, so opening a raw
``sqlite3.connect`` elsewhere would silently bypass referential integrity.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from loguru import logger

DB_PATH = Path("data_folder/jobs.sqlite")


def get_connection() -> sqlite3.Connection:
    """Open a connection with foreign-key enforcement enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database() -> None:
    """Initialize the SQLite schema if it does not already exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        for statement in _SCHEMA_STATEMENTS:
            cursor.execute(statement)
        conn.commit()

    logger.info(f"Database initialized at {DB_PATH}")


# Soft-delete columns (deleted_at) appear on every table that participates in the
# audit trail so records are retired, not destroyed. UNIQUE/foreign-key
# constraints below are only enforced because get_connection enables the pragma.
_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        company TEXT NOT NULL,
        platform TEXT NOT NULL,
        url TEXT NOT NULL,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'submitted', 'failed', 'manual_required')),
        deleted_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS applications (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES jobs(id),
        submitted_at TIMESTAMP,
        result TEXT,
        error_log TEXT,
        screenshot_path TEXT,
        current_status TEXT DEFAULT 'pending',
        needs_review BOOLEAN DEFAULT 0,
        review_priority INTEGER DEFAULT 0,
        confidence_score REAL DEFAULT 0.5,
        form_data_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        deleted_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS email_triage (
        id TEXT PRIMARY KEY,
        received_at TIMESTAMP NOT NULL,
        sender TEXT NOT NULL,
        subject TEXT NOT NULL,
        classification TEXT CHECK(classification IN ('rejection', 'interview', 'action_required', 'noise')),
        confidence_score REAL DEFAULT 0.5,
        raw_snippet TEXT,
        review_status TEXT DEFAULT 'unreviewed' CHECK(review_status IN ('unreviewed', 'reviewed_correct', 'reviewed_incorrect')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        deleted_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS manual_review_queue (
        id TEXT PRIMARY KEY,
        job_id TEXT REFERENCES jobs(id),
        application_id TEXT REFERENCES applications(id),
        question_text TEXT,
        field_name TEXT,
        application_url TEXT,
        category TEXT CHECK(category IN ('unknown_field', 'freeform_question', 'captcha_failed', 'email_flagged')),
        priority INTEGER DEFAULT 0,
        flagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        deleted_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS status_history (
        id TEXT PRIMARY KEY,
        application_id TEXT NOT NULL REFERENCES applications(id),
        old_status TEXT,
        new_status TEXT NOT NULL,
        changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        changed_by TEXT,
        is_manual BOOLEAN DEFAULT 0,
        automation_type TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS job_batches (
        id TEXT PRIMARY KEY,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        discovery_sources TEXT,
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'expired')),
        batch_size INTEGER,
        user_email TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP,
        approved_at TIMESTAMP,
        deleted_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS batch_jobs (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES job_batches(id),
        job_id TEXT NOT NULL REFERENCES jobs(id),
        position INTEGER NOT NULL,
        user_approval_status TEXT DEFAULT 'pending' CHECK(user_approval_status IN ('approved', 'rejected', 'pending')),
        approved_at TIMESTAMP,
        is_duplicate_of TEXT REFERENCES jobs(id),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        deleted_at TIMESTAMP,
        UNIQUE(batch_id, job_id),
        UNIQUE(batch_id, position)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS job_discoveries (
        id TEXT PRIMARY KEY,
        platform TEXT NOT NULL,
        job_id TEXT NOT NULL REFERENCES jobs(id),
        title TEXT NOT NULL,
        company TEXT NOT NULL,
        salary_raw TEXT,
        salary_hourly REAL,
        salary_annual REAL,
        location TEXT,
        link TEXT,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        batch_id TEXT REFERENCES job_batches(id),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        deleted_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approval_log (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES job_batches(id),
        user_email TEXT NOT NULL,
        approval_text TEXT,
        parsed_approvals TEXT,
        received_at TIMESTAMP NOT NULL,
        processed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        deleted_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_platform ON jobs(platform)",
    "CREATE INDEX IF NOT EXISTS idx_applications_job_id ON applications(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_manual_review_priority ON manual_review_queue(priority, flagged_at)",
    "CREATE INDEX IF NOT EXISTS idx_email_triage_classification ON email_triage(classification, confidence_score)",
    "CREATE INDEX IF NOT EXISTS idx_batch_jobs_batch_id ON batch_jobs(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_batch_jobs_job_id ON batch_jobs(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_job_discoveries_batch_id ON job_discoveries(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_job_discoveries_job_id ON job_discoveries(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_approval_log_batch_id ON approval_log(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_status_history_application_id ON status_history(application_id)",
)
