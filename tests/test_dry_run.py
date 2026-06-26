"""Side-by-side dry-run comparison of the Playwright and Browser Use agents.

Runs each agent against one real target in DRY-RUN mode (fills the form, takes a
screenshot, never clicks submit) and prints a cost + result comparison. This is
an opt-in integration harness, not a CI unit test:

  - It skips unless the relevant library is installed (`playwright`,
    `browser_use`) AND a target URL is provided via environment variable.
  - Provide targets you are comfortable navigating (ideally a posting you would
    actually apply to, or a vendor demo) — do NOT point it at strangers' jobs to
    submit junk; dry-run never submits, but be considerate of real forms.

Run directly for the printed comparison:

    DRY_RUN_PLAYWRIGHT_URL=https://jobs.ashbyhq.com/<co>/<id> \
    DRY_RUN_BROWSERUSE_URL=https://jobs.lever.co/<co>/<id> \
    python tests/test_dry_run.py
"""

from __future__ import annotations

import importlib.util
import os
import time
from dataclasses import dataclass
from typing import Optional

import pytest

from src.agents.base_agent import CandidateProfile, JobListing

PLAYWRIGHT_URL_ENV = "DRY_RUN_PLAYWRIGHT_URL"
BROWSERUSE_URL_ENV = "DRY_RUN_BROWSERUSE_URL"

PROFILE = CandidateProfile(
    full_name=os.environ.get("DRY_RUN_NAME", "Test Applicant"),
    email=os.environ.get("DRY_RUN_EMAIL", "test.applicant@example.com"),
    phone=os.environ.get("DRY_RUN_PHONE", "+1-555-0100"),
    resume_path=os.environ.get("DRY_RUN_RESUME", "data_folder/resume.pdf"),
    linkedin_url=os.environ.get("DRY_RUN_LINKEDIN", "https://linkedin.com/in/test"),
)


@dataclass
class DryRunRow:
    agent: str
    target: str
    status: str
    notes: str
    cost_usd: float
    seconds: float


def _library_available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _run_playwright(url: str) -> DryRunRow:
    from src.agents.playwright_agent import PlaywrightAgent

    agent = PlaywrightAgent(PROFILE, dry_run=True)
    job = JobListing(id="dryrun", title="Dry Run", company="Target", url=url, platform="ashby")
    started = time.monotonic()
    result = agent.submit_application(job, PROFILE)
    return DryRunRow(
        agent="PlaywrightAgent",
        target=url,
        status=result.status.value,
        notes=result.manual_review_notes or result.error_message or "",
        cost_usd=agent.answerer.cost.usd,
        seconds=time.monotonic() - started,
    )


def _run_browser_use(url: str) -> DryRunRow:
    from src.agents.browser_use_agent import BrowserUseAgent

    agent = BrowserUseAgent(PROFILE, dry_run=True)
    job = JobListing(id="dryrun", title="Dry Run", company="Target", url=url, platform="lever")
    started = time.monotonic()
    result = agent.submit_application(job, PROFILE)
    return DryRunRow(
        agent="BrowserUseAgent",
        target=url,
        status=result.status.value,
        notes=result.manual_review_notes or result.error_message or "",
        cost_usd=agent.cost.usd,
        seconds=time.monotonic() - started,
    )


def _format_comparison(rows: list[DryRunRow]) -> str:
    header = f"{'AGENT':<18}{'STATUS':<16}{'COST $':<10}{'SECONDS':<10}NOTES"
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row.agent:<18}{row.status:<16}{row.cost_usd:<10.4f}{row.seconds:<10.1f}{row.notes}"
        )
    return "\n".join(lines)


def _collect_rows() -> list[DryRunRow]:
    rows: list[DryRunRow] = []
    pw_url = os.environ.get(PLAYWRIGHT_URL_ENV)
    if pw_url and _library_available("playwright"):
        rows.append(_run_playwright(pw_url))
    bu_url = os.environ.get(BROWSERUSE_URL_ENV)
    if bu_url and _library_available("browser_use"):
        rows.append(_run_browser_use(bu_url))
    return rows


@pytest.mark.skipif(
    not (os.environ.get(PLAYWRIGHT_URL_ENV) and _library_available("playwright")),
    reason="Set DRY_RUN_PLAYWRIGHT_URL and install playwright to run this dry run",
)
def test_playwright_dry_run_does_not_submit():
    row = _run_playwright(os.environ[PLAYWRIGHT_URL_ENV])
    print("\n" + _format_comparison([row]))
    # Dry run must never report a real submission.
    assert row.status in ("manual_review", "failed")


@pytest.mark.skipif(
    not (os.environ.get(BROWSERUSE_URL_ENV) and _library_available("browser_use")),
    reason="Set DRY_RUN_BROWSERUSE_URL and install browser-use to run this dry run",
)
def test_browser_use_dry_run_does_not_submit():
    row = _run_browser_use(os.environ[BROWSERUSE_URL_ENV])
    print("\n" + _format_comparison([row]))
    assert row.status in ("manual_review", "failed")


if __name__ == "__main__":
    collected = _collect_rows()
    if not collected:
        print(
            "No dry runs executed. Set DRY_RUN_PLAYWRIGHT_URL and/or DRY_RUN_BROWSERUSE_URL,\n"
            "and install playwright / browser-use, then re-run."
        )
    else:
        print(_format_comparison(collected))
