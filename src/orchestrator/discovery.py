"""Job discovery from platforms (Greenhouse, Lever)."""

import httpx
import uuid
from typing import List, Optional, Dict
from loguru import logger
from src.agents.base_agent import JobListing


def discover_jobs(
    platform: str,
    board_token: Optional[str] = None,
    company: Optional[str] = None,
    filters: Optional[Dict] = None,
) -> List[JobListing]:
    """Discover jobs from platform (Greenhouse or Lever)."""
    filters = filters or {}
    logger.debug(f"Discovering jobs from {platform}")

    if platform == "greenhouse" and board_token:
        return discover_greenhouse(board_token, filters)
    elif platform == "lever" and company:
        return discover_lever(company, filters)
    else:
        logger.error(f"Unknown platform or missing credentials: {platform}")
        return []


def discover_greenhouse(board_token: str, filters: Dict) -> List[JobListing]:
    """Discover jobs from Greenhouse public API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"

    try:
        with httpx.Client() as client:
            response = client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            jobs = []
            for job in data.get("jobs", []):
                # Extract company name from nested organization object
                org = job.get("organization", {})
                company_name = org.get("name") if isinstance(org, dict) else "Unknown"

                listing = JobListing(
                    id=str(job.get("id")),
                    title=job.get("title"),
                    company=company_name or "Unknown",
                    url=job.get("absolute_url", ""),
                    platform="greenhouse",
                )
                jobs.append(listing)

            logger.info(f"Discovered {len(jobs)} jobs from Greenhouse")
            return jobs
    except httpx.TimeoutException:
        logger.error("Timeout discovering Greenhouse jobs")
        return []
    except Exception as e:
        logger.error(f"Error discovering Greenhouse jobs: {e}")
        return []


def discover_lever(company: str, filters: Dict) -> List[JobListing]:
    """Discover jobs from Lever public API."""
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"

    try:
        with httpx.Client() as client:
            response = client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            jobs = []
            for posting in data.get("postings", []):
                listing = JobListing(
                    id=posting.get("id"),
                    title=posting.get("text"),
                    company=company,
                    url=posting.get("applyUrl", ""),
                    platform="lever",
                )
                jobs.append(listing)

            logger.info(f"Discovered {len(jobs)} jobs from Lever")
            return jobs
    except httpx.TimeoutException:
        logger.error("Timeout discovering Lever jobs")
        return []
    except Exception as e:
        logger.error(f"Error discovering Lever jobs: {e}")
        return []
