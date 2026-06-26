"""Job discovery from platforms (Greenhouse, Lever)."""

import json
from typing import List, Optional, Dict
from urllib.parse import quote

import httpx
from loguru import logger

from src.agents.base_agent import JobListing

GREENHOUSE_BOARDS_BASE = "https://boards-api.greenhouse.io/v1/boards"
LEVER_POSTINGS_BASE = "https://api.lever.co/v0/postings"
REQUEST_TIMEOUT_SECONDS = 10
UNKNOWN_COMPANY = "Unknown"


def discover_jobs(
    platform: str,
    board_token: Optional[str] = None,
    company: Optional[str] = None,
    filters: Optional[Dict] = None,
) -> List[JobListing]:
    """Discover jobs from a platform (Greenhouse or Lever).

    Args:
        platform: "greenhouse" or "lever".
        board_token: Greenhouse board token (required for Greenhouse).
        company: Company slug/name. Required for Lever; for Greenhouse it labels
            the listings (the board API does not return a per-job company name).
        filters: Reserved for forward compatibility. Discovery returns the full
            board; salary/threshold filtering is applied downstream in the
            salary/digest stage, not here. A non-empty value is logged so callers
            are not misled into thinking server-side filtering occurred.

    Returns:
        Discovered job listings, or an empty list on a handled network/parse
        failure or unknown platform.
    """
    if filters:
        logger.debug(
            "discover_jobs received filters; these are applied downstream, not at discovery: {}",
            filters,
        )

    if platform == "greenhouse" and board_token:
        return discover_greenhouse(board_token, company)
    if platform == "lever" and company:
        return discover_lever(company)

    logger.error(f"Unknown platform or missing credentials: {platform}")
    return []


def discover_greenhouse(
    board_token: str, company: Optional[str] = None
) -> List[JobListing]:
    """Discover jobs from the Greenhouse public board API.

    The board API does not expose a per-job company name, so the company is
    taken from the caller-supplied value or resolved once from the board's own
    metadata. Falling back to a per-job lookup would be wrong (every job would
    read as "Unknown"), which silently collapses distinct companies during
    deduplication.
    """
    url = f"{GREENHOUSE_BOARDS_BASE}/{quote(board_token, safe='')}/jobs"

    try:
        with httpx.Client() as client:
            response = client.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()

            resolved_company = company or _fetch_greenhouse_company(client, board_token)

            jobs = []
            for job in data.get("jobs", []):
                title = job.get("title")
                if not title:
                    logger.warning(f"Skipping Greenhouse job with no title: {job.get('id')}")
                    continue

                jobs.append(
                    JobListing(
                        id=str(job.get("id")),
                        title=title,
                        company=resolved_company,
                        url=job.get("absolute_url", ""),
                        platform="greenhouse",
                    )
                )

            logger.info(f"Discovered {len(jobs)} jobs from Greenhouse")
            return jobs
    except httpx.TimeoutException:
        logger.error("Timeout discovering Greenhouse jobs")
        return []
    except httpx.HTTPError as exc:
        logger.error(f"HTTP error discovering Greenhouse jobs: {exc}")
        return []
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error(f"Malformed Greenhouse response: {exc}")
        return []


def discover_lever(company: str) -> List[JobListing]:
    """Discover jobs from the Lever public postings API."""
    url = f"{LEVER_POSTINGS_BASE}/{quote(company, safe='')}?mode=json"

    try:
        with httpx.Client() as client:
            response = client.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()

            jobs = []
            for posting in data.get("postings", []):
                title = posting.get("text")
                if not title:
                    logger.warning(f"Skipping Lever posting with no title: {posting.get('id')}")
                    continue

                jobs.append(
                    JobListing(
                        id=str(posting.get("id")),
                        title=title,
                        company=company,
                        url=posting.get("applyUrl", ""),
                        platform="lever",
                    )
                )

            logger.info(f"Discovered {len(jobs)} jobs from Lever")
            return jobs
    except httpx.TimeoutException:
        logger.error("Timeout discovering Lever jobs")
        return []
    except httpx.HTTPError as exc:
        logger.error(f"HTTP error discovering Lever jobs: {exc}")
        return []
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error(f"Malformed Lever response: {exc}")
        return []


def _fetch_greenhouse_company(client: httpx.Client, board_token: str) -> str:
    """Resolve the company name from the Greenhouse board metadata endpoint."""
    url = f"{GREENHOUSE_BOARDS_BASE}/{quote(board_token, safe='')}"
    try:
        response = client.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        name = response.json().get("name")
        return name or UNKNOWN_COMPANY
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"Could not resolve Greenhouse board company: {exc}")
        return UNKNOWN_COMPANY
