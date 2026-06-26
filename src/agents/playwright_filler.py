"""Concrete Playwright implementation of the FormFiller protocol.

Generic enough for standard ATS hosted forms (Ashby, Greenhouse): it discovers
inputs/textareas/selects, derives a human label for each, and fills by locator.
Kept separate from PlaywrightAgent so the agent's logic stays unit-testable
without a browser, and so Playwright is imported only when actually driving one.
"""

from __future__ import annotations

from typing import List, Optional

from loguru import logger

from src.agents.browser_support import FormField

PAGE_LOAD_TIMEOUT_MS = 15_000
CONFIRMATION_MARKERS = ("thank you", "application received", "we received", "successfully")


class PlaywrightFormFiller:
    """Drive a real Chromium page through a persistent (logged-in) profile."""

    def __init__(self, user_data_dir: str = "data_folder/chrome_profile", headless: bool = False):
        self.user_data_dir = user_data_dir
        self.headless = headless
        self._playwright = None
        self._context = None
        self._page = None

    def open(self, url: str) -> None:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        # Persistent context reuses cookies/login, the same way AIHawk relies on a
        # human-authenticated session rather than solving logins programmatically.
        self._context = self._playwright.chromium.launch_persistent_context(
            self.user_data_dir, headless=self.headless
        )
        self._page = self._context.new_page()
        self._page.goto(url, timeout=PAGE_LOAD_TIMEOUT_MS, wait_until="domcontentloaded")

    def page_html(self) -> str:
        return self._page.content()

    def parse_fields(self) -> List[FormField]:
        fields: List[FormField] = []
        for handle in self._page.query_selector_all("input, textarea, select"):
            field = self._field_from_handle(handle)
            if field is not None:
                fields.append(field)
        return fields

    def fill_field(self, field: FormField, value: str) -> None:
        locator = self._page.locator(field.selector).first
        if field.field_type == "select":
            locator.select_option(label=value)
        else:
            locator.fill(value)

    def upload_resume(self, field: FormField, resume_path: str) -> None:
        self._page.locator(field.selector).first.set_input_files(resume_path)

    def submit(self) -> None:
        button = self._page.locator(
            "button[type=submit], input[type=submit], button:has-text('Submit')"
        ).first
        button.click()
        self._page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT_MS)

    def confirmation_text(self) -> str:
        body = (self._page.content() or "").lower()
        return next((marker for marker in CONFIRMATION_MARKERS if marker in body), "")

    def screenshot(self, path: str) -> None:
        self._page.screenshot(path=path, full_page=True)

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()

    def _field_from_handle(self, handle) -> Optional[FormField]:
        input_type = (handle.get_attribute("type") or "").lower()
        if input_type in ("hidden", "submit", "button"):
            return None

        tag = handle.evaluate("el => el.tagName.toLowerCase()")
        field_type = self._classify(tag, input_type)
        label = self._label_for(handle)
        if not label:
            return None

        required = handle.get_attribute("required") is not None or (
            handle.get_attribute("aria-required") == "true"
        )
        return FormField(
            label=label,
            field_type=field_type,
            required=required,
            selector=self._selector_for(handle),
            options=self._options_for(handle) if field_type == "select" else [],
        )

    @staticmethod
    def _classify(tag: str, input_type: str) -> str:
        if tag == "textarea":
            return "textarea"
        if tag == "select":
            return "select"
        if input_type == "file":
            return "file"
        if input_type in ("email", "tel", "checkbox"):
            return "phone" if input_type == "tel" else input_type
        return "text"

    def _label_for(self, handle) -> str:
        for attr in ("aria-label", "placeholder", "name"):
            value = handle.get_attribute(attr)
            if value:
                return value.strip()
        field_id = handle.get_attribute("id")
        if field_id:
            label = self._page.query_selector(f"label[for='{field_id}']")
            if label:
                return (label.inner_text() or "").strip()
        return ""

    @staticmethod
    def _selector_for(handle) -> str:
        field_id = handle.get_attribute("id")
        if field_id:
            return f"#{field_id}"
        name = handle.get_attribute("name")
        if name:
            return f"[name='{name}']"
        return ""

    @staticmethod
    def _options_for(handle) -> List[str]:
        return [
            (opt.inner_text() or "").strip()
            for opt in handle.query_selector_all("option")
            if (opt.inner_text() or "").strip()
        ]
