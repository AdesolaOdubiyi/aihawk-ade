"""Tests for the candidate profile loader and rich field resolution.

Verifies that real application questions (work authorization, education, salary,
reusable essays) resolve from the profile with no LLM call.
"""

from pathlib import Path

import pytest

from src.agents.browser_support import AnswerCache, FormAnswerer, FormField
from src.agents.profile_loader import load_candidate_profile

PROFILE_YAML = """
contact:
  full_name: "Jane Doe"
  email: "jane@example.com"
  phone: "+1-555-0100"
  location: "Boston, MA"
links:
  linkedin: "https://linkedin.com/in/janedoe"
  github: "https://github.com/janedoe"
resume_path: "data_folder/resume.pdf"
work_eligibility:
  work_authorization: "Authorized to work in the US"
  requires_sponsorship: "No"
experience:
  years_experience: "3"
education:
  - school: "Northeastern University"
    degree: "B.S. Computer Science"
    graduation_year: "2027"
preferences:
  salary_expectation: "120000"
common_answers:
  "Why do you want to work here?": "I admire the team's quality bar."
"""


class StubLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, prompt):
        self.calls += 1
        return "LLM-FALLBACK", 0, 0


@pytest.fixture
def profile(tmp_path):
    path = tmp_path / "candidate_profile.yaml"
    path.write_text(PROFILE_YAML, encoding="utf-8")
    return load_candidate_profile(path)


def _field(label):
    return FormField(label=label, field_type="text", required=True, selector="#x")


def test_loader_populates_qa_and_education(profile):
    assert profile.full_name == "Jane Doe"
    assert profile.github_url == "https://github.com/janedoe"
    assert profile.location == "Boston, MA"
    assert profile.qa["work_authorization"] == "Authorized to work in the US"
    assert profile.qa["requires_sponsorship"] == "No"
    assert profile.qa["years_experience"] == "3"
    assert profile.qa["school"] == "Northeastern University"
    assert profile.qa["salary_expectation"] == "120000"


def test_missing_profile_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_candidate_profile(tmp_path / "does_not_exist.yaml")


class TestRichResolution:
    def _answerer(self, profile, tmp_path):
        self.llm = StubLLM()
        return FormAnswerer(profile, AnswerCache(tmp_path / "cache.json"), llm=self.llm)

    def test_work_authorization_resolves_without_llm(self, profile, tmp_path):
        answerer = self._answerer(profile, tmp_path)
        result = answerer.resolve(_field("Are you legally authorized to work in the US?"))
        assert result == "Authorized to work in the US"
        assert self.llm.calls == 0

    def test_sponsorship_and_experience_resolve(self, profile, tmp_path):
        answerer = self._answerer(profile, tmp_path)
        assert answerer.resolve(_field("Will you require sponsorship?")) == "No"
        assert answerer.resolve(_field("Years of experience")) == "3"
        assert self.llm.calls == 0

    def test_education_field_resolves(self, profile, tmp_path):
        answerer = self._answerer(profile, tmp_path)
        assert answerer.resolve(_field("University")) == "Northeastern University"

    def test_reusable_essay_matches_by_gist(self, profile, tmp_path):
        answerer = self._answerer(profile, tmp_path)
        # Different punctuation/case than the YAML key, same gist.
        result = answerer.resolve(_field("why do you want to work here"))
        assert result == "I admire the team's quality bar."
        assert self.llm.calls == 0

    def test_truly_novel_question_falls_to_llm(self, profile, tmp_path):
        answerer = self._answerer(profile, tmp_path)
        result = answerer.resolve(_field("Describe your favorite debugging war story"))
        assert result == "LLM-FALLBACK"
        assert self.llm.calls == 1
