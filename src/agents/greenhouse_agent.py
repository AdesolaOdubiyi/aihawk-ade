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


class GreenhouseAgent(APIAgent):
    """Greenhouse job board API integration."""

    BASE_URL = "https://boards-api.greenhouse.io/v1"

    def __init__(self, board_token: str):
        super().__init__("GreenhouseAgent")
        self.board_token = board_token
        self.field_mapping = self._load_field_mapping()

    def _load_field_mapping(self) -> dict:
        """Load field name variants from YAML."""
        # TODO: Load from data_folder/field_mapping.yaml
        return {
            "first_name": ["first_name", "firstName", "first name"],
            "last_name": ["last_name", "lastName", "last name"],
            "email": ["email", "email_address", "emailAddress"],
            "phone": ["phone", "phone_number", "phoneNumber", "mobile"],
        }

    def fetch_form_definition(self, job_id: str) -> FormDefinition:
        """Fetch job form schema from Greenhouse API."""
        logger.debug(f"Fetching form definition for job {job_id}")
        url = f"{self.BASE_URL}/boards/{self.board_token}/jobs/{job_id}"
        try:
            with httpx.Client() as client:
                response = client.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
                job = data.get("job", {})
                questions = job.get("questions", [])

                fields = {}
                required_fields = []
                for q in questions:
                    field_id = str(q.get("id"))
                    fields[field_id] = {
                        "label": q.get("label"),
                        "type": q.get("type"),
                        "required": q.get("required", False),
                    }
                    if q.get("required"):
                        required_fields.append(field_id)

                return FormDefinition(
                    fields=fields,
                    required_fields=required_fields,
                    submission_url=f"{self.BASE_URL}/boards/{self.board_token}/jobs/{job_id}",
                )
        except httpx.TimeoutException as e:
            logger.error(f"Timeout fetching form definition: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"API error fetching form: {e}")
            raise

    def submit_application(
        self, job: JobListing, profile: CandidateProfile
    ) -> SubmissionResult:
        """Submit application via Greenhouse API."""
        logger.debug(f"Submitting application for {job.title} at {job.company}")
        result_id = str(uuid.uuid4())
        self.unfilled_required = []

        try:
            # Fetch form definition
            form_def = self.fetch_form_definition(job.id)

            # Build form data (may have unfilled required fields)
            form_data = self._build_form_data(
                profile, form_def, job.id
            )

            # If there are unfilled required fields, flag for manual review (don't fail)
            if self.unfilled_required:
                logger.warning(
                    f"Application has {len(self.unfilled_required)} unfilled required fields",
                    job_id=job.id,
                    unfilled=self.unfilled_required,
                )
                return SubmissionResult(
                    status=ApplicationResult.MANUAL_REVIEW,
                    application_id=result_id,
                    error_message=f"{len(self.unfilled_required)} required fields unmapped",
                    manual_review_notes=f"Unmapped required fields: {[u['label'] for u in self.unfilled_required]}",
                    fields_filled=form_data,
                )

            # Submit with retry
            submission_result = self._submit_with_retry(form_def.submission_url, form_data)

            if submission_result["success"]:
                logger.info(
                    f"Successfully submitted application for {job.title}",
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
                    manual_review_notes="Form submission failed, requires manual review",
                )
        except httpx.TimeoutException:
            logger.error(f"Timeout submitting application to {job.url}")
            return SubmissionResult(
                status=ApplicationResult.FAILED,
                error_message="API timeout (retried once)",
            )
        except Exception as e:
            logger.error(f"Error submitting application: {e}")
            return SubmissionResult(
                status=ApplicationResult.FAILED,
                error_message=str(e),
            )

    def _build_form_data(
        self, profile: CandidateProfile, form_def: FormDefinition, job_id: str
    ) -> dict:
        """Build form data from profile and form definition."""
        form_data = {}
        self.unfilled_required = []

        for field_id, field_info in form_def.fields.items():
            field_label = field_info.get("label", "").lower()
            field_type = field_info.get("type")
            is_required = field_info.get("required", False)

            # Try to match field to profile
            value = self._match_field_value(field_label, profile)

            if value:
                # Validate field value
                if not self._validate_field_value(value, field_type):
                    if is_required:
                        self.unfilled_required.append(
                            {"field_id": field_id, "label": field_info.get("label"), "reason": "invalid_value"}
                        )
                    continue

                form_data[field_id] = value
            elif is_required:
                # Unknown required field
                self.unfilled_required.append(
                    {"field_id": field_id, "label": field_info.get("label"), "reason": "no_match"}
                )

        if self.unfilled_required:
            logger.warning(
                f"Unknown required fields: {self.unfilled_required}",
                job_id=job_id,
            )

        return form_data

    def _match_field_value(self, field_label: str, profile: CandidateProfile) -> Optional[str]:
        """Match field label to profile value."""
        field_label_lower = field_label.lower()

        if any(x in field_label_lower for x in ["first", "given"]):
            return profile.full_name.split()[0]
        elif any(x in field_label_lower for x in ["last", "family", "surname"]):
            return profile.full_name.split()[-1]
        elif "email" in field_label_lower:
            return profile.email
        elif "phone" in field_label_lower:
            return profile.phone
        elif "linkedin" in field_label_lower:
            return profile.linkedin_url
        return None

    def _validate_field_value(self, value: str, field_type: str) -> bool:
        """Validate field value based on type."""
        if not value:
            return False

        if field_type == "email":
            return "@" in value and "." in value.split("@")[1]
        elif field_type in ["phone", "phone_number"]:
            return len(value.replace("-", "").replace(" ", "").replace("+", "")) >= 10
        elif field_type == "short_text":
            return len(value) > 0
        else:
            return True

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
                    result = response.json()
                    return {
                        "success": True,
                        "application_id": result.get("application_id", str(uuid.uuid4())),
                    }
            except httpx.TimeoutException:
                if attempt < max_retries:
                    logger.warning(
                        f"Timeout on attempt {attempt + 1}, retrying after 30s..."
                    )
                    time.sleep(30)
                else:
                    logger.error(f"Timeout after {max_retries + 1} attempts")
                    raise
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error: {e}")
                return {"success": False, "error": str(e)}
            except Exception as e:
                logger.error(f"Error submitting: {e}")
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "Max retries exceeded"}
