"""Detect duplicate jobs across platforms."""

import hashlib
from typing import List, Dict, Set, Tuple
from loguru import logger
from src.agents.base_agent import JobListing


class JobDeduplicator:
    """Detect and track duplicate jobs across platforms."""

    def __init__(self, primary_platform_order: List[str] = None):
        """Initialize with platform priority order."""
        self.primary_platform_order = primary_platform_order or ["greenhouse", "lever", "ashby"]
        self.seen_hashes: Dict[str, str] = {}  # hash -> job_id
        self.duplicates: Dict[str, List[str]] = {}  # job_id -> [duplicate_ids]

    def add_job(self, job: JobListing) -> Tuple[str, bool]:
        """Add job and check if duplicate.

        Returns: (job_id, is_duplicate)
        """
        job_hash = self._hash_job(job)

        if job_hash in self.seen_hashes:
            primary_id = self.seen_hashes[job_hash]
            if primary_id not in self.duplicates:
                self.duplicates[primary_id] = []
            self.duplicates[primary_id].append(job.id)
            logger.debug(f"Job {job.id} is duplicate of {primary_id}")
            return job.id, True
        else:
            self.seen_hashes[job_hash] = job.id
            logger.debug(f"Job {job.id} is unique")
            return job.id, False

    def get_primary_job(self, job_id: str) -> str:
        """Get primary job ID if this is a duplicate."""
        for primary, duplicates in self.duplicates.items():
            if job_id in duplicates:
                return primary
        return job_id

    def filter_non_duplicates(self, jobs: List[JobListing]) -> List[JobListing]:
        """Filter to only primary (non-duplicate) jobs."""
        non_dups = []
        for job in jobs:
            _, is_dup = self.add_job(job)
            if not is_dup:
                non_dups.append(job)
        return non_dups

    def _hash_job(self, job: JobListing) -> str:
        """Create hash from job metadata (title, company, location if available)."""
        # Use title + company as fingerprint (location not always available)
        fingerprint = f"{job.title}|{job.company}".lower()
        return hashlib.md5(fingerprint.encode()).hexdigest()
