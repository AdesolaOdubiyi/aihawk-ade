"""Parse user email replies to extract job approvals."""

import re
from typing import List, Dict, Optional
from loguru import logger


def parse_approvals(
    email_text: str,
    total_jobs: int,
    return_all: bool = False,
) -> List[str] | Dict:
    """Parse user email reply to extract approved job IDs.

    Handles formats like:
    - "APPROVE: 1, 3, 5"
    - "APPROVE all"
    - "REJECT: 2, 4"
    - Mixed approval + rejection

    Args:
        email_text: User's email reply
        total_jobs: Total jobs in batch (for validation)
        return_all: If True, return {approved, rejected, unanswered}

    Returns:
        List of approved job IDs, or Dict if return_all=True
    """
    email_lower = email_text.lower()

    # Check for "APPROVE all"
    if re.search(r'approve\s+all', email_lower):
        approved = [str(i) for i in range(1, total_jobs + 1)]
        if return_all:
            return {
                "approved": approved,
                "rejected": [],
                "unanswered": [],
            }
        return approved

    # Check for "REJECT all"
    if re.search(r'reject\s+all', email_lower):
        rejected = [str(i) for i in range(1, total_jobs + 1)]
        if return_all:
            return {
                "approved": [],
                "rejected": rejected,
                "unanswered": [str(i) for i in range(1, total_jobs + 1)],
            }
        return []

    # Parse "APPROVE: 1, 3, 5" format
    approved = []
    rejected = []

    # Extract APPROVE ids
    approve_match = re.search(r'approve:\s*([\d,\s]+)', email_lower)
    if approve_match:
        ids_str = approve_match.group(1)
        approved = _parse_id_list(ids_str)

    # Extract REJECT ids
    reject_match = re.search(r'reject:\s*([\d,\s]+)', email_lower)
    if reject_match:
        ids_str = reject_match.group(1)
        rejected = _parse_id_list(ids_str)

    if return_all:
        all_ids = set(str(i) for i in range(1, total_jobs + 1))
        unanswered = list(all_ids - set(approved) - set(rejected))
        return {
            "approved": approved,
            "rejected": rejected,
            "unanswered": sorted(unanswered),
        }

    logger.debug(f"Parsed approvals: {approved}, rejections: {rejected}")
    return approved


def _parse_id_list(ids_str: str) -> List[str]:
    """Parse comma-separated or space-separated IDs."""
    # Split by comma or space, clean up
    ids = re.split(r'[,\s]+', ids_str.strip())
    ids = [id.strip() for id in ids if id.strip().isdigit()]
    return ids
