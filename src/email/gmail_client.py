from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


@dataclass
class Email:
    id: str
    sender: str
    subject: str
    body: str
    received_at: datetime
    is_unread: bool


class GmailClient:
    """Gmail API client for email triage.

    Note: Full Gmail OAuth implementation pending.
    Current implementation uses mock for testing.
    """

    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path
        self.service = None
        logger.info("GmailClient initialized (OAuth not yet implemented)")

    def authenticate(self) -> bool:
        """Authenticate with Gmail API."""
        try:
            # TODO: Implement OAuth 2.0 flow
            # from google.auth.transport.requests import Request
            # from google.oauth2.service_account import Credentials
            logger.warning("Gmail OAuth not implemented yet; using mock")
            return False
        except Exception as e:
            logger.error(f"Gmail auth failed: {e}")
            return False

    def fetch_unread_emails(self, limit: int = 50) -> List[Email]:
        """Fetch unread emails from Gmail inbox."""
        if not self.service:
            logger.warning("Gmail not authenticated; returning empty list")
            return []

        try:
            # TODO: Implement Gmail API call
            # results = self.service.users().messages().list(
            #     userId='me', q='is:unread', maxResults=limit
            # ).execute()
            logger.warning("fetch_unread_emails not implemented yet")
            return []
        except Exception as e:
            logger.error(f"Error fetching emails: {e}")
            return []

    def fetch_email_body(self, message_id: str) -> Optional[str]:
        """Fetch full email body."""
        if not self.service:
            return None

        try:
            # TODO: Implement Gmail API call
            logger.warning("fetch_email_body not implemented yet")
            return None
        except Exception as e:
            logger.error(f"Error fetching email body: {e}")
            return None

    def mark_as_read(self, message_id: str) -> bool:
        """Mark email as read."""
        if not self.service:
            return False

        try:
            # TODO: Implement Gmail API call
            logger.warning("mark_as_read not implemented yet")
            return False
        except Exception as e:
            logger.error(f"Error marking email as read: {e}")
            return False


class MockGmailClient(GmailClient):
    """Mock Gmail client for testing without OAuth."""

    def __init__(self):
        super().__init__()
        logger.info("Using MockGmailClient for testing")

    def authenticate(self) -> bool:
        """Mock authentication."""
        self.service = {}
        return True

    def fetch_unread_emails(self, limit: int = 50) -> List[Email]:
        """Return mock emails for testing."""
        return [
            Email(
                id="mock-1",
                sender="recruiter@company.com",
                subject="We'd like to schedule an interview",
                body="Hi, we are excited to move forward with your application...",
                received_at=datetime.now(),
                is_unread=True,
            ),
            Email(
                id="mock-2",
                sender="noreply@company.com",
                subject="Unfortunately, we decided to move forward with another candidate",
                body="We appreciate your interest, but...",
                received_at=datetime.now(),
                is_unread=True,
            ),
        ]

    def fetch_email_body(self, message_id: str) -> Optional[str]:
        """Return mock body."""
        return "Mock email body"

    def mark_as_read(self, message_id: str) -> bool:
        """Mock mark as read."""
        return True
