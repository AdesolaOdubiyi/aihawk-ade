"""Load a candidate profile from YAML into a CandidateProfile.

Flattens the human-friendly sectioned YAML (contact / links / work_eligibility /
education / preferences / eeo / common_answers) into the canonical `qa` map the
FormAnswerer resolves against, so a form question routes to the right answer
without any per-application configuration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml
from loguru import logger

from src.agents.base_agent import CandidateProfile
from src.forms.field_mapping import normalize_label

DEFAULT_PROFILE_PATH = Path("data_folder/candidate_profile.yaml")

# Sections whose key/value pairs map directly onto canonical qa entries.
_QA_SECTIONS = ("work_eligibility", "experience", "preferences", "eeo")


def load_candidate_profile(path: Path = DEFAULT_PROFILE_PATH) -> CandidateProfile:
    """Build a CandidateProfile from the YAML at `path`.

    Raises FileNotFoundError if the profile is missing — callers should surface a
    clear "copy candidate_profile.example.yaml" message rather than running with
    an empty profile.
    """
    if not Path(path).exists():
        raise FileNotFoundError(
            f"No candidate profile at {path}. Copy candidate_profile.example.yaml "
            f"to candidate_profile.yaml and fill it in."
        )

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    contact = raw.get("contact", {})
    links = raw.get("links", {})
    education = raw.get("education", []) or []

    profile = CandidateProfile(
        full_name=contact.get("full_name", ""),
        email=contact.get("email", ""),
        phone=contact.get("phone", ""),
        resume_path=raw.get("resume_path", ""),
        linkedin_url=links.get("linkedin"),
        github_url=links.get("github"),
        portfolio_url=links.get("portfolio"),
        location=contact.get("location"),
        education=education,
        qa=_build_qa(raw, education),
    )
    logger.info(f"Loaded candidate profile for {profile.full_name} from {path}")
    return profile


def _build_qa(raw: dict, education: List[dict]) -> Dict[str, str]:
    """Collapse the qa-bearing sections and education into one canonical map."""
    qa: Dict[str, str] = {}

    for section in _QA_SECTIONS:
        for key, value in (raw.get(section) or {}).items():
            if value:
                qa[key] = str(value)

    if education:
        most_recent = education[0]
        for key in ("school", "degree", "field_of_study", "graduation_year", "gpa"):
            if most_recent.get(key):
                qa[key] = str(most_recent[key])

    for question, answer in (raw.get("common_answers") or {}).items():
        if answer:
            qa[normalize_label(question)] = str(answer)

    return qa
