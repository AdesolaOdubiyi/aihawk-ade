import sqlite3
from pathlib import Path
from loguru import logger


DB_PATH = Path("data_folder/jobs.sqlite")


def init_database():
    """Initialize SQLite schema if not exists."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Jobs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            platform TEXT NOT NULL,
            url TEXT NOT NULL,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'submitted', 'failed', 'manual_required'))
        )
    """)

    # Applications table
    cursor.execute("""
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Email triage table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_triage (
            id TEXT PRIMARY KEY,
            received_at TIMESTAMP NOT NULL,
            sender TEXT NOT NULL,
            subject TEXT NOT NULL,
            classification TEXT CHECK(classification IN ('rejection', 'interview', 'action_required', 'noise')),
            confidence_score REAL DEFAULT 0.5,
            raw_snippet TEXT,
            review_status TEXT DEFAULT 'unreviewed' CHECK(review_status IN ('unreviewed', 'reviewed_correct', 'reviewed_incorrect')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Manual review queue table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS manual_review_queue (
            id TEXT PRIMARY KEY,
            job_id TEXT REFERENCES jobs(id),
            application_id TEXT REFERENCES applications(id),
            question_text TEXT,
            field_name TEXT,
            application_url TEXT,
            category TEXT CHECK(category IN ('unknown_field', 'freeform_question', 'captcha_failed', 'email_flagged')),
            priority INTEGER DEFAULT 0,
            flagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Status history table (audit trail)
    cursor.execute("""
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
    """)

    # Job batches (discovery runs)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_batches (
            id TEXT PRIMARY KEY,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            discovery_sources TEXT,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'expired')),
            batch_size INTEGER,
            user_email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            approved_at TIMESTAMP
        )
    """)

    # Batch jobs (individual jobs in a batch)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS batch_jobs (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES job_batches(id),
            job_id TEXT NOT NULL REFERENCES jobs(id),
            user_approval_status TEXT DEFAULT 'pending' CHECK(user_approval_status IN ('approved', 'rejected', 'pending')),
            approved_at TIMESTAMP,
            is_duplicate_of TEXT REFERENCES jobs(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Job discoveries (raw discovery records)
    cursor.execute("""
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Approval log (user email replies)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approval_log (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES job_batches(id),
            user_email TEXT NOT NULL,
            approval_text TEXT,
            parsed_approvals TEXT,
            received_at TIMESTAMP NOT NULL,
            processed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_platform ON jobs(platform)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_applications_job_id ON applications(job_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manual_review_priority ON manual_review_queue(priority, flagged_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_triage_classification ON email_triage(classification, confidence_score)")

    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")
