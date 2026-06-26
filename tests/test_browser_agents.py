"""Unit tests for the browser-tier agents and their support code.

These run with no browser and no LLM: the Playwright/Browser Use drives are
replaced by fakes, and the LLM by a stub. Real end-to-end behavior (a live
browser + model against a real target) is covered by test_dry_run.py.
"""

from pathlib import Path

import pytest

from src.agents.base_agent import ApplicationResult, CandidateProfile, JobListing
from src.agents.browser_support import (
    AnswerCache,
    CostLedger,
    FormAnswerer,
    FormField,
    detect_blocker,
)
from src.agents.browser_use_agent import BrowserUseAgent, BrowserUseOutcome
from src.agents.playwright_agent import DRY_RUN_NOTE, PlaywrightAgent

PROFILE = CandidateProfile(
    full_name="Jane Doe",
    email="jane@example.com",
    phone="+1-555-0100",
    resume_path="/resume.pdf",
    linkedin_url="https://linkedin.com/in/janedoe",
)
JOB = JobListing(id="1", title="Engineer", company="Acme", url="https://x/apply", platform="ashby")


class StubLLM:
    """Returns a fixed answer and fixed token counts; records prompts."""

    def __init__(self, answer: str = "", input_tokens: int = 0, output_tokens: int = 0):
        self.answer = answer
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.prompts = []

    def complete(self, prompt: str):
        self.prompts.append(prompt)
        return self.answer, self.input_tokens, self.output_tokens


class FakeFiller:
    """In-memory FormFiller: records calls, never touches a browser."""

    def __init__(self, html: str, fields, confirmation: str = "", raise_on_open: bool = False):
        self._html = html
        self._fields = fields
        self._confirmation = confirmation
        self._raise_on_open = raise_on_open
        self.filled = {}
        self.uploaded = []
        self.submitted = False
        self.closed = False

    def open(self, url):
        if self._raise_on_open:
            raise RuntimeError("navigation failed")

    def page_html(self):
        return self._html

    def parse_fields(self):
        return self._fields

    def fill_field(self, field, value):
        self.filled[field.label] = value

    def upload_resume(self, field, resume_path):
        self.uploaded.append(resume_path)

    def submit(self):
        self.submitted = True

    def confirmation_text(self):
        return self._confirmation

    def screenshot(self, path):
        pass

    def close(self):
        self.closed = True


def _text_field(label, required=True):
    return FormField(label=label, field_type="text", required=required, selector=f"#{label}")


class TestDetectBlocker:
    def test_flags_hcaptcha(self):
        assert detect_blocker('<div class="h-captcha" data-sitekey="x">') == "captcha"

    def test_flags_cloudflare_challenge(self):
        assert detect_blocker("Just a moment... /cdn-cgi/challenge") == "bot_protection"

    def test_flags_login_wall(self):
        assert detect_blocker("Please sign in to apply") == "login_required"

    def test_clean_page_is_not_blocked(self):
        assert detect_blocker("<form><input name='email'></form>") is None


class TestAnswerCache:
    def test_roundtrip_and_normalization(self, tmp_path):
        cache = AnswerCache(tmp_path / "answers.json")
        cache.put("Why do you want this job?", "Because I love it")
        # Different whitespace/case resolves to the same cached answer.
        assert cache.get("why  do you WANT this job?") == "Because I love it"

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "answers.json"
        AnswerCache(path).put("Q", "A")
        assert AnswerCache(path).get("Q") == "A"


class TestFormAnswerer:
    def _answerer(self, llm):
        return FormAnswerer(PROFILE, AnswerCache(Path("/nonexistent/answers.json")), llm=llm)

    def test_resolves_profile_fields_without_llm(self):
        llm = StubLLM(answer="SHOULD-NOT-BE-CALLED")
        answerer = self._answerer(llm)

        assert answerer.resolve(_text_field("First Name")) == "Jane"
        assert answerer.resolve(_text_field("Last Name")) == "Doe"
        assert answerer.resolve(_text_field("Email Address")) == "jane@example.com"
        assert answerer.resolve(_text_field("LinkedIn URL")) == "https://linkedin.com/in/janedoe"
        assert llm.prompts == []  # never reached the LLM

    def test_novel_question_uses_llm_and_tracks_cost(self, tmp_path):
        llm = StubLLM(answer="I admire the mission.", input_tokens=120, output_tokens=15)
        answerer = FormAnswerer(PROFILE, AnswerCache(tmp_path / "a.json"), llm=llm)

        answer = answerer.resolve(_text_field("Why do you want to work here?"))

        assert answer == "I admire the mission."
        assert answerer.cost.llm_calls == 1
        assert answerer.cost.input_tokens == 120
        # Local default model is free.
        assert answerer.cost.usd == 0.0

    def test_llm_failure_yields_none(self, tmp_path):
        class BoomLLM:
            def complete(self, prompt):
                raise RuntimeError("ollama down")

        answerer = FormAnswerer(PROFILE, AnswerCache(tmp_path / "a.json"), llm=BoomLLM())
        assert answerer.resolve(_text_field("Essay question")) is None


class TestPlaywrightAgent:
    def _agent(self, filler, dry_run=True, llm=None):
        answerer = FormAnswerer(
            PROFILE, AnswerCache(Path("/nonexistent/a.json")), llm=llm or StubLLM(answer="")
        )
        return PlaywrightAgent(
            PROFILE, dry_run=dry_run, filler_factory=lambda: filler, answerer=answerer
        )

    def test_captcha_routes_to_manual_review(self):
        filler = FakeFiller('<div class="g-recaptcha">', [])
        result = self._agent(filler).submit_application(JOB, PROFILE)
        assert result.status is ApplicationResult.MANUAL_REVIEW
        assert "captcha" in result.manual_review_notes
        assert not filler.submitted

    def test_unfilled_required_field_blocks_submit(self):
        # An essay field the stub LLM answers with "" (-> None) stays unfilled.
        filler = FakeFiller("<form>", [_text_field("Cover letter essay", required=True)])
        result = self._agent(filler).submit_application(JOB, PROFILE)
        assert result.status is ApplicationResult.MANUAL_REVIEW
        assert "Cover letter essay" in result.manual_review_notes
        assert not filler.submitted

    def test_dry_run_fills_but_never_submits(self):
        filler = FakeFiller("<form>", [_text_field("Email")])
        result = self._agent(filler, dry_run=True).submit_application(JOB, PROFILE)
        assert result.status is ApplicationResult.MANUAL_REVIEW
        assert result.manual_review_notes == DRY_RUN_NOTE
        assert filler.filled == {"Email": "jane@example.com"}
        assert not filler.submitted

    def test_real_submit_succeeds_on_confirmation(self):
        filler = FakeFiller("<form>", [_text_field("Email")], confirmation="thank you")
        result = self._agent(filler, dry_run=False).submit_application(JOB, PROFILE)
        assert result.status is ApplicationResult.SUCCESS
        assert filler.submitted

    def test_real_submit_without_confirmation_is_manual_review(self):
        filler = FakeFiller("<form>", [_text_field("Email")], confirmation="")
        result = self._agent(filler, dry_run=False).submit_application(JOB, PROFILE)
        assert result.status is ApplicationResult.MANUAL_REVIEW
        assert filler.submitted

    def test_filler_error_is_contained(self):
        filler = FakeFiller("", [], raise_on_open=True)
        result = self._agent(filler).submit_application(JOB, PROFILE)
        assert result.status is ApplicationResult.MANUAL_REVIEW
        assert filler.closed  # cleanup still ran


class TestBrowserUseAgent:
    def _agent(self, outcome=None, dry_run=True, raises=False):
        class FakeRunner:
            def run(self, task):
                if raises:
                    raise RuntimeError("agent crashed")
                return outcome

        return BrowserUseAgent(PROFILE, dry_run=dry_run, runner=FakeRunner())

    def test_blocker_routes_to_manual_review(self):
        outcome = BrowserUseOutcome(succeeded=False, blocker="captcha_or_login")
        result = self._agent(outcome).submit_application(JOB, PROFILE)
        assert result.status is ApplicationResult.MANUAL_REVIEW
        assert "captcha_or_login" in result.manual_review_notes

    def test_dry_run_never_reports_success(self):
        outcome = BrowserUseOutcome(succeeded=True, final_text="filled")
        result = self._agent(outcome, dry_run=True).submit_application(JOB, PROFILE)
        assert result.status is ApplicationResult.MANUAL_REVIEW

    def test_real_run_success(self):
        outcome = BrowserUseOutcome(succeeded=True, input_tokens=500, output_tokens=50)
        agent = self._agent(outcome, dry_run=False)
        result = agent.submit_application(JOB, PROFILE)
        assert result.status is ApplicationResult.SUCCESS
        assert agent.cost.input_tokens == 500
        assert agent.cost.usd == 0.0  # local model

    def test_runner_error_is_contained(self):
        result = self._agent(raises=True).submit_application(JOB, PROFILE)
        assert result.status is ApplicationResult.MANUAL_REVIEW
        assert "Unexpected error" in result.manual_review_notes


def test_cost_ledger_prices_hosted_model():
    ledger = CostLedger(input_price=1.0 / 1_000_000, output_price=5.0 / 1_000_000)
    ledger.add(1_000_000, 1_000_000)
    assert ledger.usd == pytest.approx(6.0)
