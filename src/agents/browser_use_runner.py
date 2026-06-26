"""Live Browser Use runner — wraps the `browser_use` library.

Isolated from BrowserUseAgent so the agent's logic stays testable without the
library or a browser, and so `browser_use` (and a model backend) are imported
only when actually running. This is the local integration point: it constructs a
model, runs one navigation task, and maps the library's result onto the
agent-facing `BrowserUseOutcome`.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from src.agents.browser_support import (
    DEFAULT_ANSWER_MODEL,
    DEFAULT_OLLAMA_HOST,
    detect_blocker,
)
from src.agents.browser_use_agent import BrowserUseOutcome

_BLOCKER_TEXT_MARKERS = ("captcha", "log in", "login", "sign in", "verify you are human")
MAX_AGENT_STEPS = 30


class LiveBrowserUseRunner:
    """Runs a task through `browser_use.Agent` on a local-first model."""

    def __init__(self, model: str = DEFAULT_ANSWER_MODEL, ollama_host: str = DEFAULT_OLLAMA_HOST):
        self.model = model
        self.ollama_host = ollama_host

    def run(self, task: str) -> BrowserUseOutcome:
        return asyncio.run(self._run_async(task))

    async def _run_async(self, task: str) -> BrowserUseOutcome:
        from browser_use import Agent  # lazy: optional heavy dependency

        agent = Agent(task=task, llm=self._build_llm(), max_actions_per_step=1)
        history = await agent.run(max_steps=MAX_AGENT_STEPS)

        final_text = self._final_text(history)
        return BrowserUseOutcome(
            succeeded=self._is_done(history),
            final_text=final_text,
            blocker=self._blocker_from(final_text),
            input_tokens=self._tokens(history, "input"),
            output_tokens=self._tokens(history, "output"),
        )

    def _build_llm(self):
        """Build a local-first chat model for the agent loop.

        Tries browser_use's own Ollama chat wrapper, then langchain's, so a local
        free model is used by default; swap the model string for a hosted one.
        """
        try:
            from browser_use.llm import ChatOllama  # type: ignore

            return ChatOllama(model=self.model, host=self.ollama_host)
        except ImportError:
            from langchain_ollama import ChatOllama  # type: ignore

            return ChatOllama(model=self.model, base_url=self.ollama_host)

    @staticmethod
    def _final_text(history) -> str:
        getter = getattr(history, "final_result", None)
        if callable(getter):
            return getter() or ""
        return str(history)

    @staticmethod
    def _is_done(history) -> bool:
        getter = getattr(history, "is_done", None)
        return bool(getter()) if callable(getter) else False

    @staticmethod
    def _blocker_from(final_text: str) -> str | None:
        html_blocker = detect_blocker(final_text)
        if html_blocker:
            return html_blocker
        lowered = (final_text or "").lower()
        if any(marker in lowered for marker in _BLOCKER_TEXT_MARKERS):
            return "captcha_or_login"
        return None

    @staticmethod
    def _tokens(history, kind: str) -> int:
        # Token accounting varies by library version; absence reports zero rather
        # than guessing. On a local model the dollar cost is zero regardless.
        attr = "total_input_tokens" if kind == "input" else "total_output_tokens"
        getter = getattr(history, attr, None)
        try:
            return int(getter()) if callable(getter) else 0
        except Exception as exc:  # never let usage accounting break a real run
            logger.debug(f"Could not read {attr}: {exc}")
            return 0
