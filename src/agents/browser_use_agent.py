"""Browser Use (LLM agent loop) application agent for dynamic sites.

Use this where the DOM is variable or JS-heavy enough that fixed selectors are
brittle (Lever, LinkedIn Easy Apply, anything new): an LLM agent navigates by
intent instead of selectors, trading a little per-run reliability for far less
selector maintenance. Defaults to a free local model; the navigation loop is the
only real token cost, and it stays $0 on a local backend.

Same reliability contract as PlaywrightAgent: captcha/login -> MANUAL_REVIEW,
dry_run never submits, unexpected errors -> MANUAL_REVIEW (never silent).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from loguru import logger

from src.agents.base_agent import (
    ApplicationResult,
    CandidateProfile,
    JobListing,
    SubmissionResult,
)
from src.agents.browser_agent import BrowserAgent, FormDefinition
from src.agents.browser_support import CostLedger, DEFAULT_ANSWER_MODEL, price_for

DRY_RUN_NOTE = "DRY RUN: agent filled the form but was instructed not to submit"


@dataclass
class BrowserUseOutcome:
    """Structured result of one Browser Use run, decoupled from the library API."""

    succeeded: bool
    final_text: str = ""
    blocker: Optional[str] = None  # captcha / login / None
    input_tokens: int = 0
    output_tokens: int = 0
    screenshot_path: Optional[str] = None


class BrowserUseRunner(Protocol):
    """Runs one navigation task and reports a structured outcome.

    The real implementation wraps the `browser_use` library; tests inject a fake.
    """

    def run(self, task: str) -> BrowserUseOutcome: ...


class BrowserUseAgent(BrowserAgent):
    """Apply via an LLM-driven browser agent loop."""

    def __init__(
        self,
        profile: CandidateProfile,
        dry_run: bool = True,
        runner: Optional[BrowserUseRunner] = None,
        model: str = DEFAULT_ANSWER_MODEL,
    ):
        super().__init__("BrowserUseAgent")
        self.profile = profile
        self.dry_run = dry_run
        self.runner = runner if runner is not None else self._default_runner(model)
        input_price, output_price = price_for(model)
        self.cost = CostLedger(input_price=input_price, output_price=output_price)

    def parse_form(self) -> FormDefinition:
        """The agent discovers fields itself; no separate parse step."""
        raise NotImplementedError("BrowserUseAgent discovers fields during the run")

    def handle_email_verification(self, timeout_seconds: int = 300) -> bool:
        return False

    def submit_application(
        self, job: JobListing, profile: CandidateProfile
    ) -> SubmissionResult:
        """Run the agent loop to a terminal outcome, never raising past here."""
        task = self._build_task(job)
        try:
            outcome = self.runner.run(task)
        except Exception as exc:  # boundary: a runner failure must not crash the batch
            logger.error(f"Browser Use run errored for {job.url}: {exc}")
            return SubmissionResult(
                status=ApplicationResult.MANUAL_REVIEW,
                error_message=str(exc),
                manual_review_notes="Unexpected error during agent run",
            )

        self.cost.add(outcome.input_tokens, outcome.output_tokens)
        return self._result_from_outcome(outcome)

    def _result_from_outcome(self, outcome: BrowserUseOutcome) -> SubmissionResult:
        if outcome.blocker:
            return SubmissionResult(
                status=ApplicationResult.MANUAL_REVIEW,
                manual_review_notes=f"Blocked by {outcome.blocker}",
                screenshot_path=outcome.screenshot_path,
            )
        if self.dry_run:
            return SubmissionResult(
                status=ApplicationResult.MANUAL_REVIEW,
                manual_review_notes=DRY_RUN_NOTE,
                screenshot_path=outcome.screenshot_path,
            )
        if outcome.succeeded:
            return SubmissionResult(
                status=ApplicationResult.SUCCESS,
                screenshot_path=outcome.screenshot_path,
            )
        return SubmissionResult(
            status=ApplicationResult.MANUAL_REVIEW,
            manual_review_notes=outcome.final_text or "Agent did not confirm submission",
            screenshot_path=outcome.screenshot_path,
        )

    def _build_task(self, job: JobListing) -> str:
        submit_clause = (
            "Fill every field but DO NOT click the final submit button. Stop once the "
            "form is complete and report what you filled."
            if self.dry_run
            else "Fill every field and submit the application."
        )
        return (
            f"Go to {job.url} and apply for '{job.title}' at {job.company}.\n"
            f"Candidate: {self.profile.full_name}, {self.profile.email}, "
            f"{self.profile.phone}, LinkedIn {self.profile.linkedin_url}.\n"
            f"Resume file: {self.profile.resume_path}.\n"
            f"If you hit a captcha, login wall, or anything you cannot complete, stop and "
            f"say so explicitly. {submit_clause}"
        )

    def _default_runner(self, model: str) -> BrowserUseRunner:
        from src.agents.browser_use_runner import LiveBrowserUseRunner

        return LiveBrowserUseRunner(model=model)
