"""Playwright-driven application agent for stable, predictable ATS forms.

Use this for platforms whose DOM is consistent enough to drive with selectors
(Ashby, Greenhouse hosted forms): it is cheaper and more reliable per run than a
full LLM agent loop because navigation is deterministic and the LLM is only ever
touched for novel free-form answers.

Reliability rules, in order:
  1. Any captcha / bot-wall / login gate -> MANUAL_REVIEW (never attempt a submit).
  2. Any unfilled required field -> MANUAL_REVIEW (never submit a partial form).
  3. dry_run -> fill everything, screenshot, but never click submit.
  4. Any unexpected error -> MANUAL_REVIEW with the detail (never a silent failure).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Protocol

from loguru import logger

from src.agents.base_agent import (
    ApplicationResult,
    CandidateProfile,
    JobListing,
    SubmissionResult,
)
from src.agents.browser_agent import BrowserAgent, FormDefinition
from src.agents.browser_support import (
    AnswerCache,
    DEFAULT_ANSWER_MODEL,
    FormAnswerer,
    FormField,
    detect_blocker,
)

DEFAULT_CACHE_PATH = Path("data_folder/answers_cache.json")
DEFAULT_SCREENSHOT_DIR = Path("data_folder/screenshots")
DRY_RUN_NOTE = "DRY RUN: form filled but not submitted"


class FormFiller(Protocol):
    """The browser operations the agent needs, isolated for testing.

    The real implementation (PlaywrightFormFiller) drives Playwright; tests pass
    a fake so the agent's decision logic can be exercised without a browser.
    """

    def open(self, url: str) -> None: ...
    def page_html(self) -> str: ...
    def parse_fields(self) -> List[FormField]: ...
    def fill_field(self, field: FormField, value: str) -> None: ...
    def upload_resume(self, field: FormField, resume_path: str) -> None: ...
    def submit(self) -> None: ...
    def confirmation_text(self) -> str: ...
    def screenshot(self, path: str) -> None: ...
    def close(self) -> None: ...


class PlaywrightAgent(BrowserAgent):
    """Fill and submit a stable ATS form via Playwright."""

    def __init__(
        self,
        profile: CandidateProfile,
        dry_run: bool = True,
        filler_factory: Optional[Callable[[], FormFiller]] = None,
        cache_path: Path = DEFAULT_CACHE_PATH,
        answer_model: str = DEFAULT_ANSWER_MODEL,
        answerer: Optional[FormAnswerer] = None,
    ):
        super().__init__("PlaywrightAgent")
        self.profile = profile
        self.dry_run = dry_run
        self.filler_factory = filler_factory or self._default_filler_factory
        self.answerer = answerer or FormAnswerer(
            profile, AnswerCache(cache_path), model=answer_model
        )

    def parse_form(self) -> FormDefinition:
        """Not used directly — fields are parsed during submit_application."""
        raise NotImplementedError("PlaywrightAgent parses fields within submit_application")

    def handle_email_verification(self, timeout_seconds: int = 300) -> bool:
        """Email verification is treated as a manual step, not automated here."""
        return False

    def submit_application(
        self, job: JobListing, profile: CandidateProfile
    ) -> SubmissionResult:
        """Drive the form to a terminal outcome, never raising past this method."""
        filler = self.filler_factory()
        try:
            return self._run(filler, job)
        except Exception as exc:  # boundary: unexpected DOM/driver error -> manual review
            logger.error(f"Playwright submission errored for {job.url}: {exc}")
            return SubmissionResult(
                status=ApplicationResult.MANUAL_REVIEW,
                error_message=str(exc),
                manual_review_notes="Unexpected error during automated fill",
            )
        finally:
            self._close_quietly(filler)

    def _run(self, filler: FormFiller, job: JobListing) -> SubmissionResult:
        filler.open(job.url)

        blocker = detect_blocker(filler.page_html())
        if blocker:
            return SubmissionResult(
                status=ApplicationResult.MANUAL_REVIEW,
                manual_review_notes=f"Blocked by {blocker}",
            )

        unfilled_required = self._fill_fields(filler)
        if unfilled_required:
            return SubmissionResult(
                status=ApplicationResult.MANUAL_REVIEW,
                error_message=f"{len(unfilled_required)} required fields unanswered",
                manual_review_notes=f"Unanswered required fields: {unfilled_required}",
            )

        if self.dry_run:
            shot = self._capture_screenshot(filler, job)
            return SubmissionResult(
                status=ApplicationResult.MANUAL_REVIEW,
                manual_review_notes=DRY_RUN_NOTE,
                screenshot_path=shot,
            )

        return self._submit_and_verify(filler, job)

    def _fill_fields(self, filler: FormFiller) -> List[str]:
        """Fill every field; return the labels of required fields left unanswered."""
        unfilled_required: List[str] = []
        for field in filler.parse_fields():
            if field.field_type == "file":
                filler.upload_resume(field, self.profile.resume_path)
                continue

            value = self.answerer.resolve(field)
            if value is None:
                if field.required:
                    unfilled_required.append(field.label)
                continue
            filler.fill_field(field, value)
        return unfilled_required

    def _submit_and_verify(self, filler: FormFiller, job: JobListing) -> SubmissionResult:
        filler.submit()
        confirmation = filler.confirmation_text()
        shot = self._capture_screenshot(filler, job)
        if confirmation:
            logger.info(f"Submitted {job.title} at {job.company}")
            return SubmissionResult(status=ApplicationResult.SUCCESS, screenshot_path=shot)
        return SubmissionResult(
            status=ApplicationResult.MANUAL_REVIEW,
            manual_review_notes="No confirmation after submit",
            screenshot_path=shot,
        )

    def _capture_screenshot(self, filler: FormFiller, job: JobListing) -> Optional[str]:
        DEFAULT_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = str(DEFAULT_SCREENSHOT_DIR / f"{job.platform}-{job.id}.png")
        try:
            filler.screenshot(path)
            return path
        except Exception as exc:  # screenshot is best-effort evidence, not load-bearing
            logger.warning(f"Could not capture screenshot: {exc}")
            return None

    def _close_quietly(self, filler: FormFiller) -> None:
        try:
            filler.close()
        except Exception as exc:  # cleanup must not mask the real result
            logger.warning(f"Error closing browser: {exc}")

    def _default_filler_factory(self) -> FormFiller:
        from src.agents.playwright_filler import PlaywrightFormFiller

        return PlaywrightFormFiller()
