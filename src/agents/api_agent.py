from abc import abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional
from src.agents.base_agent import Agent, JobListing, CandidateProfile, SubmissionResult
from loguru import logger


@dataclass
class FormDefinition:
    fields: Dict[str, Any]
    required_fields: list
    submission_url: str


class APIAgent(Agent):
    """Abstract base for API-driven job application platforms (Greenhouse, Lever)."""

    def __init__(self, name: str):
        super().__init__(name)

    @abstractmethod
    def fetch_form_definition(self, job_id: str) -> FormDefinition:
        """Fetch form schema from API before submission."""
        pass

    @abstractmethod
    def submit_application(
        self, job: JobListing, profile: CandidateProfile
    ) -> SubmissionResult:
        """Submit application via API."""
        pass
