from abc import abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional
from src.agents.base_agent import Agent, JobListing, CandidateProfile, SubmissionResult
from loguru import logger


@dataclass
class FormDefinition:
    fields: Dict[str, Any]
    required_fields: list


class BrowserAgent(Agent):
    """Abstract base for browser-driven job application platforms (Ashby, LinkedIn)."""

    def __init__(self, name: str):
        super().__init__(name)

    @abstractmethod
    def parse_form(self) -> FormDefinition:
        """Parse form DOM to extract field definitions."""
        pass

    @abstractmethod
    def handle_email_verification(self, timeout_seconds: int = 300) -> bool:
        """Handle email verification step if required (blocks until verified or timeout)."""
        pass

    @abstractmethod
    def submit_application(
        self, job: JobListing, profile: CandidateProfile
    ) -> SubmissionResult:
        """Submit application via browser automation."""
        pass
