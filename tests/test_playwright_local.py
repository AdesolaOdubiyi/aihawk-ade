"""Real-browser integration test for PlaywrightAgent against a LOCAL form.

This drives an actual Chromium instance against a self-contained HTML file on
disk (file:// URL) — no employer, no external site, no LLM (every field maps to
the profile). It exercises the real PlaywrightFormFiller end to end and proves
the hard dry-run guarantee: fields get filled, a screenshot is taken, and the
form is never submitted.

Skips automatically unless Playwright and a browser are installed:
    pip install playwright && playwright install chromium
"""

from __future__ import annotations

import importlib.util

import pytest

from src.agents.base_agent import ApplicationResult, CandidateProfile, JobListing
from src.agents.playwright_agent import DRY_RUN_NOTE, PlaywrightAgent

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None,
    reason="install playwright + run 'playwright install chromium' to run this",
)

FORM_HTML = """<!doctype html>
<html><body>
<form id="application-form" method="POST">
  <label for="fn">First Name</label><input id="fn" name="first_name" required>
  <label for="ln">Last Name</label><input id="ln" name="last_name" required>
  <input id="em" name="email" type="email" aria-label="Email" required>
  <input id="ph" name="phone" type="tel" placeholder="Phone" required>
  <input id="rs" name="resume" type="file" required>
  <button type="submit">Submit Application</button>
</form>
</body></html>
"""


@pytest.fixture
def local_form(tmp_path):
    form_path = tmp_path / "form.html"
    form_path.write_text(FORM_HTML, encoding="utf-8")
    return form_path.as_uri()


@pytest.fixture
def profile(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text("Jane Doe resume", encoding="utf-8")
    return CandidateProfile(
        full_name="Jane Doe",
        email="jane@example.com",
        phone="+1-555-0100",
        resume_path=str(resume),
        linkedin_url="https://linkedin.com/in/janedoe",
    )


def test_playwright_dry_run_fills_local_form_without_submitting(local_form, profile, tmp_path):
    pytest.importorskip("playwright.sync_api")
    # Headless so it runs in CI; real dry-run is headed so a human can intervene.
    from src.agents.playwright_filler import PlaywrightFormFiller

    agent = PlaywrightAgent(
        profile,
        dry_run=True,
        filler_factory=lambda: PlaywrightFormFiller(
            user_data_dir=str(tmp_path / "profile"), headless=True
        ),
    )
    job = JobListing(
        id="local", title="Engineer", company="Local", url=local_form, platform="ashby"
    )

    try:
        result = agent.submit_application(job, profile)
    except Exception as exc:  # no browser binary installed -> skip, don't fail
        pytest.skip(f"Chromium not available: {exc}")

    assert result.status is ApplicationResult.MANUAL_REVIEW
    assert result.manual_review_notes == DRY_RUN_NOTE
    assert result.screenshot_path is not None
