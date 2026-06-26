import httpx
import time
import uuid
from typing import Optional
from loguru import logger
from src.agents.api_agent import APIAgent, FormDefinition
from src.agents.base_agent import (
    JobListing,
    CandidateProfile,
    SubmissionResult,
    ApplicationResult,
)
from src.forms.field_mapping import load_field_mapping


class LeverAgent(APIAgent):
    """Lever job board API integration."""

    BASE_URL = "https://api.lever.co/v0"
    SUBMIT_BASE = "https://jobs.lever.co"

    def __init__(self, company: str):
        super().__init__("LeverAgent")
        self.company = company
        self.field_mapping = load_field_mapping()

    def fetch_form_definition(self, job_id: str) -> FormDefinition:
        """Fetch job posting from Lever API."""
        logger.debug(f"Fetching form definition for job {job_id}")
        url = f"{self.BASE_URL}/postings/{self.company}?mode=json"

        try:
            with httpx.Client() as client:
                response = client.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
                postings = data.get("postings", [])

                # Find the specific job
                job_posting = next(
                    (p for p in postings if p.get("id") == job_id), None
                )
                if not job_posting:
                    raise ValueError(f"Job {job_id} not found")

                # Extract form fields from posting (Lever API doesn't expose form schema directly)
                # We infer required fields based on standard Lever form fields
                required_fields = ["name", "email"]
                if job_posting.get("applyUrl"):
                    # Will need to handle form dynamically on submission
                    pass

                return FormDefinition(
                    fields={
                        "name": {"type": "text", "required": True},
                        "email": {"type": "email", "required": True},
                    },
                    required_fields=required_fields,
                    submission_url=job_posting.get("applyUrl", ""),
                )
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching job: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching job: {e}")
            raise

    def submit_application(
        self, job: JobListing, profile: CandidateProfile
    ) -> SubmissionResult:
        """Submit application via Lever API.

        Note: Gate 1 (endpoint validation) must be completed before full implementation.
        This is placeholder pending manual endpoint test.
        """
        logger.debug(f"Submitting application to Lever for {job.title} at {job.company}")
        result_id = str(uuid.uuid4())

        try:
            # Build form data
            form_data = {
                "name": profile.full_name,
                "email": profile.email,
                "phone": profile.phone,
            }

            # Submit application
            submission_result = self._submit_with_retry(job.url, form_data)

            if submission_result["success"]:
                logger.info(
                    f"Successfully submitted to Lever for {job.title}",
                    application_id=submission_result["application_id"],
                )
                return SubmissionResult(
                    status=ApplicationResult.SUCCESS,
                    application_id=submission_result["application_id"],
                    fields_filled=form_data,
                )
            else:
                return SubmissionResult(
                    status=ApplicationResult.MANUAL_REVIEW,
                    error_message=submission_result.get("error"),
                    manual_review_notes="Lever submission requires manual review (Gate 1 endpoint may not be gated)",
                )
        except Exception as e:
            logger.error(f"Error submitting to Lever: {e}")
            return SubmissionResult(
                status=ApplicationResult.FAILED,
                error_message=str(e),
            )

    def _submit_with_retry(self, url: str, form_data: dict, max_retries: int = 1) -> dict:
        """Submit form with retry logic."""
        for attempt in range(max_retries + 1):
            try:
                with httpx.Client() as client:
                    response = client.post(
                        url,
                        data=form_data,
                        timeout=10,
                    )
                    response.raise_for_status()

                    # Lever doesn't return JSON on success; check status code
                    if response.status_code in [200, 201, 204]:
                        return {
                            "success": True,
                            "application_id": str(uuid.uuid4()),
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"Unexpected status: {response.status_code}",
                        }
            except httpx.TimeoutException:
                if attempt < max_retries:
                    logger.warning("Timeout, retrying after 30s...")
                    time.sleep(30)
                else:
                    logger.error("Timeout after retries")
                    raise
            except Exception as e:
                logger.error(f"Error submitting: {e}")
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "Max retries exceeded"}
