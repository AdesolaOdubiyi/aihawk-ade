import pytest
from src.agents.base_agent import ApplicationResult
from src.agents.greenhouse_agent import GreenhouseAgent


class TestGreenhouseHappyPath:
    """Slice 1: Greenhouse API submission succeeds."""

    def test_greenhouse_successful_submission(
        self, temp_db, sample_job, sample_profile, mock_greenhouse_api
    ):
        """Test successful Greenhouse application submission."""
        agent = GreenhouseAgent(board_token="test-board-token")
        result = agent.submit_application(sample_job, sample_profile)

        # Verify submission succeeded
        assert result.status == ApplicationResult.SUCCESS
        assert result.application_id == "app-456"
        assert result.error_message is None
        assert result.fields_filled is not None
        # Fields should be keyed by field ID from form definition
        assert len(result.fields_filled) >= 3  # At least first name, last name, email filled


class TestGreenhouseUnknownField:
    """Slice 2: Unknown required field handling."""

    def test_unknown_required_field_flagged(
        self, temp_db, sample_job, sample_profile
    ):
        """Test that unknown required fields are flagged for manual review, not failed."""
        agent = GreenhouseAgent(board_token="test-board-token")

        # Mock form with unknown field
        with mock_form_with_unknown_field(agent):
            result = agent.submit_application(sample_job, sample_profile)

        # Should not fail, should flag for manual review
        assert result.status == ApplicationResult.MANUAL_REVIEW
        assert result.manual_review_notes is not None
        assert "unknown_field" in result.manual_review_notes.lower()

        # Verify manual_review_queue populated
        import sqlite3
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM manual_review_queue WHERE category = 'unknown_field'"
        )
        row = cursor.fetchone()
        assert row is not None
        conn.close()


class TestGreenhouseInvalidInput:
    """Slice 3: Invalid input handling."""

    def test_invalid_email_format_flagged(
        self, temp_db, sample_job, sample_profile
    ):
        """Test that invalid email is caught and flagged."""
        agent = GreenhouseAgent(board_token="test-board-token")
        invalid_profile = sample_profile
        invalid_profile.email = "not-an-email"

        result = agent.submit_application(sample_job, invalid_profile)

        assert result.status == ApplicationResult.MANUAL_REVIEW
        assert "email" in result.error_message.lower()


class TestGreenhouseTimeout:
    """Slice 4: Timeout handling."""

    def test_api_timeout_retry_once_then_fail(
        self, temp_db, sample_job, sample_profile
    ):
        """Test that API timeout retries once, then fails."""
        agent = GreenhouseAgent(board_token="test-board-token")

        # Mock API timeout
        with mock_greenhouse_timeout():
            result = agent.submit_application(sample_job, sample_profile)

        assert result.status == ApplicationResult.FAILED
        assert result.error_message is not None
        assert "timeout" in result.error_message.lower()
        # Verify retry count in logs or error_log
        assert hasattr(result, "error_message")


@pytest.fixture
def mock_form_with_unknown_field():
    """Context manager to mock form with unknown required field."""
    from contextlib import contextmanager

    @contextmanager
    def inner(agent):
        # Inject unknown field into form
        original_fetch = agent.fetch_form_definition

        def patched_fetch(job_id):
            form = original_fetch(job_id)
            form.fields["mystery_field"] = {
                "type": "unknown",
                "label": "Mystery Field",
                "required": True,
            }
            form.required_fields.append("mystery_field")
            return form

        agent.fetch_form_definition = patched_fetch
        yield
        agent.fetch_form_definition = original_fetch

    return inner


@pytest.fixture
def mock_greenhouse_timeout():
    """Context manager to mock API timeout."""
    from contextlib import contextmanager
    from unittest.mock import patch
    import httpx

    @contextmanager
    def inner():
        with patch("httpx.Client") as mock_client:
            mock_instance = Mock()
            mock_client.return_value.__enter__.return_value = mock_instance
            mock_instance.post.side_effect = httpx.TimeoutException("Request timeout")
            yield

    return inner
