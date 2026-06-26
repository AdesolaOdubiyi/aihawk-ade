"""Shared support for browser-tier application agents.

Holds the pieces both the Playwright and Browser Use agents depend on: a
persistent answer cache, anti-bot/login detection, an LLM-backed form answerer
with cost tracking, and the small value types they exchange. Keeping these here
(rather than in either agent) lets the two agents stay thin and share behavior.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from loguru import logger

from src.agents.base_agent import CandidateProfile
from src.forms.field_mapping import find_field_variant, load_field_mapping

# Form filling is cheap work, so the default LLM backend is a free local model
# (Ollama). Hosted models are supported by swapping the backend; prices below let
# the dry-run harness report a realistic dollar cost when one is used. USD per
# token (input, output). Anything not listed is treated as free (local).
DEFAULT_ANSWER_MODEL = "llama3.2:3b"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
MODEL_PRICING: Dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00 / 1_000_000, 5.00 / 1_000_000),
    "gpt-4o-mini": (0.15 / 1_000_000, 0.60 / 1_000_000),
    "claude-opus-4-8": (5.00 / 1_000_000, 25.00 / 1_000_000),
}
REQUEST_TIMEOUT_SECONDS = 60


def price_for(model: str) -> tuple[float, float]:
    """Return (input, output) USD-per-token for a model; (0, 0) if local/free."""
    return MODEL_PRICING.get(model, (0.0, 0.0))

# Substrings that mark an anti-bot wall or a login gate on a fetched page.
_BLOCKER_MARKERS = {
    "captcha": ("h-captcha", "hcaptcha", "g-recaptcha", "recaptcha", "data-sitekey", "turnstile"),
    "bot_protection": ("cf-challenge", "challenge-platform", "/cdn-cgi/challenge", "just a moment"),
    "login_required": ("please sign in", "log in to continue", "sign in to apply", "session expired"),
}

# Canonical fields answerable directly from the candidate profile.
_PROFILE_FIELDS = {"full_name", "first_name", "last_name", "email", "phone", "linkedin_url"}


@dataclass
class FormField:
    """A single fillable field discovered on an application form."""

    label: str
    field_type: str  # text | email | phone | textarea | select | file | checkbox
    required: bool
    selector: str
    options: List[str] = field(default_factory=list)


@dataclass
class CostLedger:
    """Running token and dollar cost for one application attempt.

    Prices default to zero (local model), so a fully local run reports $0.00.
    """

    input_price: float = 0.0
    output_price: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0

    @property
    def usd(self) -> float:
        return self.input_tokens * self.input_price + self.output_tokens * self.output_price

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.llm_calls += 1


def detect_blocker(page_html: str) -> Optional[str]:
    """Return a blocker category (captcha/bot_protection/login_required) or None.

    This is the gate that routes a page to MANUAL_REVIEW instead of attempting an
    automated submit. It is deliberately conservative: any marker match wins.
    """
    haystack = (page_html or "").lower()
    for category, markers in _BLOCKER_MARKERS.items():
        if any(marker in haystack for marker in markers):
            logger.warning(f"Detected {category} on page; routing to manual review")
            return category
    return None


class AnswerLLM(Protocol):
    """Minimal interface the answerer needs from an LLM backend."""

    def complete(self, prompt: str) -> tuple[str, int, int]:
        """Return (answer_text, input_tokens, output_tokens)."""
        ...


class OllamaAnswerLLM:
    """Free, local answer backend over the Ollama HTTP API.

    Requires a running Ollama daemon with the model pulled. If it is unreachable,
    `complete` raises and the answerer degrades to leaving the field unfilled
    (which routes a required field to manual review) — never a hard failure.
    """

    def __init__(self, model: str = DEFAULT_ANSWER_MODEL, host: str = DEFAULT_OLLAMA_HOST):
        self.model = model
        self.host = host.rstrip("/")

    def complete(self, prompt: str) -> tuple[str, int, int]:
        import httpx  # lazy: keeps the module importable without a live daemon

        response = httpx.post(
            f"{self.host}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", ""), data.get("prompt_eval_count", 0), data.get("eval_count", 0)


class AnswerCache:
    """JSON-backed store of prior question -> answer pairs.

    Answers are keyed by a normalized hash of the question so trivially different
    phrasings reuse the same answer and avoid repeat LLM calls.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._answers: Dict[str, str] = self._load()

    def get(self, question: str) -> Optional[str]:
        return self._answers.get(self._key(question))

    def put(self, question: str, answer: str) -> None:
        self._answers[self._key(question)] = answer
        self._save()

    def _load(self) -> Dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"Could not read answer cache {self.path}: {exc}")
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._answers, indent=2), encoding="utf-8")

    @staticmethod
    def _key(question: str) -> str:
        normalized = re.sub(r"\s+", " ", (question or "").strip()).lower()
        return hashlib.sha256(normalized.encode()).hexdigest()


class FormAnswerer:
    """Resolve a field to a value via profile mapping, cache, then LLM.

    The three tiers are ordered cheapest-first: a direct profile field costs
    nothing, a cache hit costs nothing, and only a genuinely novel free-form
    question reaches the LLM. Every LLM call is recorded in the cost ledger.
    """

    def __init__(
        self,
        profile: CandidateProfile,
        cache: AnswerCache,
        llm: Optional[AnswerLLM] = None,
        model: str = DEFAULT_ANSWER_MODEL,
    ):
        self.profile = profile
        self.cache = cache
        self.llm = llm if llm is not None else OllamaAnswerLLM(model=model)
        self.field_mapping = load_field_mapping()
        input_price, output_price = price_for(model)
        self.cost = CostLedger(input_price=input_price, output_price=output_price)

    def resolve(self, field: FormField) -> Optional[str]:
        """Return a value for the field, or None if it cannot be answered."""
        direct = self._from_profile(field.label)
        if direct is not None:
            return direct

        cached = self.cache.get(field.label)
        if cached is not None:
            logger.debug(f"Answer cache hit for: {field.label}")
            return cached

        answer = self._from_llm(field)
        if answer:
            self.cache.put(field.label, answer)
        return answer

    def _from_profile(self, label: str) -> Optional[str]:
        canonical = find_field_variant(label, self.field_mapping)
        if canonical not in _PROFILE_FIELDS:
            return self._infer_profile_field(label)
        return self._profile_value(canonical)

    def _infer_profile_field(self, label: str) -> Optional[str]:
        """Fall back to substring matching when the label isn't an exact variant."""
        lowered = label.lower()
        if any(token in lowered for token in ("first name", "given name")):
            return self._name_part(first=True)
        if any(token in lowered for token in ("last name", "surname", "family name")):
            return self._name_part(first=False)
        if "email" in lowered:
            return self.profile.email
        if "phone" in lowered or "mobile" in lowered:
            return self.profile.phone
        if "linkedin" in lowered:
            return self.profile.linkedin_url
        return None

    def _profile_value(self, canonical: str) -> Optional[str]:
        if canonical == "full_name":
            return self.profile.full_name
        if canonical == "first_name":
            return self._name_part(first=True)
        if canonical == "last_name":
            return self._name_part(first=False)
        if canonical == "email":
            return self.profile.email
        if canonical == "phone":
            return self.profile.phone
        if canonical == "linkedin_url":
            return self.profile.linkedin_url
        return None

    def _name_part(self, first: bool) -> Optional[str]:
        parts = (self.profile.full_name or "").strip().split()
        if not parts:
            return None
        return parts[0] if first else parts[-1]

    def _from_llm(self, field: FormField) -> Optional[str]:
        prompt = self._build_prompt(field)
        try:
            answer, input_tokens, output_tokens = self.llm.complete(prompt)
        except Exception as exc:  # boundary: an LLM failure must not abort the fill
            logger.error(f"LLM answer failed for '{field.label}': {exc}")
            return None
        self.cost.add(input_tokens, output_tokens)
        return answer.strip() or None

    def _build_prompt(self, field: FormField) -> str:
        options = f"\nChoose exactly one of: {', '.join(field.options)}" if field.options else ""
        return (
            "You are filling a job application on behalf of this candidate.\n"
            f"Name: {self.profile.full_name}\n"
            f"Email: {self.profile.email}\n"
            f"Phone: {self.profile.phone}\n"
            f"LinkedIn: {self.profile.linkedin_url}\n\n"
            f"Answer this application field concisely and truthfully. "
            f"Reply with ONLY the answer value, no preamble.{options}\n\n"
            f"Field: {field.label}"
        )
