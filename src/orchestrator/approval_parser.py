"""Parse user email replies to extract job approvals.

Security note: parsing alone does NOT authorize anything. Approvals drive
auto-submission of real job applications, and the monitored inbox is reachable
by anyone. The orchestrator MUST call ``is_authorized_sender`` against the
reply's ``From`` address (and ideally confirm the reply is in-reply-to the
digest's message-id) BEFORE acting on any parsed result.
"""

import re
from typing import Dict, Iterable, List, Optional, Union

from loguru import logger

# Bulk commands must lead their own line so prose like "don't approve all of
# them, just 1 and 3" cannot trigger a batch-wide action.
APPROVE_ALL_PATTERN = re.compile(r'^\s*approve\s+all\b', re.MULTILINE)
REJECT_ALL_PATTERN = re.compile(r'^\s*reject\s+all\b', re.MULTILINE)
APPROVE_LIST_PATTERN = re.compile(r'approve:\s*([\d,\s]+)')
REJECT_LIST_PATTERN = re.compile(r'reject:\s*([\d,\s]+)')


def is_authorized_sender(sender: str, authorized_emails: Iterable[str]) -> bool:
    """Return True only if the reply's sender is a configured owner address.

    Compares the bare email case-insensitively. This is a necessary precondition
    for honoring approvals, not a complete spoofing defense; pair it with
    transport-level checks (SPF/DKIM, in-reply-to the digest message-id).
    """
    if not sender:
        return False

    normalized_sender = _extract_email_address(sender).lower()
    if not normalized_sender:
        return False

    authorized = {email.strip().lower() for email in authorized_emails if email}
    return normalized_sender in authorized


def parse_approvals(
    email_text: str,
    total_jobs: int,
    return_all: bool = False,
) -> Union[List[str], Dict]:
    """Parse a user email reply into approved job IDs.

    Handles "APPROVE: 1, 3, 5", "APPROVE all", "REJECT: 2, 4", and mixed replies.

    Args:
        email_text: User's email reply body.
        total_jobs: Total jobs in the batch (used to validate ID ranges).
        return_all: If True, return {approved, rejected, unanswered}.

    Returns:
        List of approved job IDs, or a dict when return_all is True.
    """
    email_lower = email_text.lower()

    if APPROVE_ALL_PATTERN.search(email_lower):
        approved = [str(i) for i in range(1, total_jobs + 1)]
        if return_all:
            return {"approved": approved, "rejected": [], "unanswered": []}
        return approved

    if REJECT_ALL_PATTERN.search(email_lower):
        if return_all:
            all_ids = [str(i) for i in range(1, total_jobs + 1)]
            return {"approved": [], "rejected": all_ids, "unanswered": list(all_ids)}
        return []

    approved = _extract_ids(APPROVE_LIST_PATTERN, email_lower, total_jobs)
    rejected = _extract_ids(REJECT_LIST_PATTERN, email_lower, total_jobs)

    if return_all:
        all_ids = {str(i) for i in range(1, total_jobs + 1)}
        unanswered = sorted(all_ids - set(approved) - set(rejected), key=int)
        return {"approved": approved, "rejected": rejected, "unanswered": unanswered}

    logger.debug(f"Parsed approvals: {approved}, rejections: {rejected}")
    return approved


def _extract_ids(pattern: re.Pattern, email_lower: str, total_jobs: int) -> List[str]:
    """Run a list-command pattern and return validated IDs, or an empty list."""
    match = pattern.search(email_lower)
    if not match:
        return []
    return _parse_id_list(match.group(1), total_jobs=total_jobs)


def _parse_id_list(ids_str: str, total_jobs: Optional[int] = None) -> List[str]:
    """Parse comma/space-separated IDs, keeping only those within range."""
    raw_tokens = re.split(r'[,\s]+', ids_str.strip())
    digit_tokens = [token for token in raw_tokens if token.isdigit()]

    if total_jobs is None:
        return digit_tokens

    valid_range = {str(i) for i in range(1, total_jobs + 1)}
    in_range = [token for token in digit_tokens if token in valid_range]
    if len(in_range) < len(digit_tokens):
        logger.warning(f"Some IDs were out of range (max: {total_jobs})")
    return in_range


def _extract_email_address(sender: str) -> str:
    """Pull the bare address from a "Name <addr@host>" or raw-address sender."""
    match = re.search(r'<([^>]+)>', sender)
    return (match.group(1) if match else sender).strip()
