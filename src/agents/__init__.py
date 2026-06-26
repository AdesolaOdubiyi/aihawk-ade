from .base_agent import Agent, ApplicationResult, JobListing, CandidateProfile, SubmissionResult
from .api_agent import APIAgent, FormDefinition as APIFormDefinition
from .browser_agent import BrowserAgent, FormDefinition as BrowserFormDefinition
from .greenhouse_agent import GreenhouseAgent

__all__ = [
    "Agent",
    "ApplicationResult",
    "JobListing",
    "CandidateProfile",
    "SubmissionResult",
    "APIAgent",
    "BrowserAgent",
    "APIFormDefinition",
    "BrowserFormDefinition",
    "GreenhouseAgent",
]
