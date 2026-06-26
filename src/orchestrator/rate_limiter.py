"""Rate limit handling for API discovery."""

import time
from typing import Optional
from loguru import logger


class RateLimitHandler:
    """Handle 429 (Too Many Requests) responses."""

    def __init__(self, max_retries: int = 5, initial_backoff: float = 1.0):
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.paused_until: Optional[float] = None

    def handle_rate_limit(self, retry_after: Optional[int] = None) -> bool:
        """Handle 429 response.

        Args:
            retry_after: Seconds from Retry-After header (if available)

        Returns:
            True if should retry, False if should give up (manual queue)
        """
        wait_seconds = retry_after or 600  # Default 10 min if no header

        logger.warning(f"Rate limited. Pausing for {wait_seconds}s")
        self.paused_until = time.time() + wait_seconds

        return False  # Don't auto-retry; move to manual queue

    def is_paused(self) -> bool:
        """Check if a rate-limit pause is currently active (no side effects)."""
        return self.paused_until is not None and time.time() < self.paused_until

    def retry_with_backoff(self, attempt: int) -> Optional[float]:
        """Calculate backoff delay for retry attempt.

        Exponential backoff: 1s, 2s, 4s, 8s, 16s

        Args:
            attempt: Attempt number (0-indexed)

        Returns:
            Seconds to wait before retry
        """
        if attempt >= self.max_retries:
            return None  # Give up

        delay = self.initial_backoff * (2 ** attempt)
        # Add jitter: ±20%
        jitter = delay * 0.2 * (2 * (time.time() % 1) - 1)
        return max(0, delay + jitter)
