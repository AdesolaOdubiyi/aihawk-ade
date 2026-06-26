from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
from loguru import logger


class ApplicationResult(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


@dataclass
class JobListing:
    id: str
    title: str
    company: str
    url: str
    platform: str


@dataclass
class CandidateProfile:
    """Everything needed to fill a job application.

    Core contact fields are typed; the long tail of application questions (work
    authorization, salary, EEO, reusable essay answers, ...) lives in `qa`, keyed
    by canonical question name, so new questions never require a schema change.
    `education` is a list of dicts (school, degree, field_of_study, graduation_year, gpa).
    """

    full_name: str
    email: str
    phone: str
    resume_path: str
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    location: Optional[str] = None
    education: List[dict] = field(default_factory=list)
    qa: dict = field(default_factory=dict)
    extra_fields: dict = None


@dataclass
class SubmissionResult:
    status: ApplicationResult
    application_id: Optional[str] = None
    error_message: Optional[str] = None
    screenshot_path: Optional[str] = None
    fields_filled: dict = None
    manual_review_notes: Optional[str] = None


class Agent(ABC):
    def __init__(self, name: str):
        self.name = name
        logger.debug(f"Initializing {name}")

    @abstractmethod
    def submit_application(
        self, job: JobListing, profile: CandidateProfile
    ) -> SubmissionResult:
        pass

    def _log_submission(self, job: JobListing, result: SubmissionResult):
        logger.info(
            f"{self.name}: {result.status.value} for {job.title} at {job.company}",
            application_id=result.application_id,
            error=result.error_message,
        )
