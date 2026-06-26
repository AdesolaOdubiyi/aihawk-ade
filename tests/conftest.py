import pytest
import sqlite3
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from src.agents.base_agent import JobListing, CandidateProfile, ApplicationResult
from src.database.schema import DB_PATH, init_database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Use temporary SQLite database for tests."""
    test_db = tmp_path / "test_jobs.sqlite"
    monkeypatch.setattr("src.database.schema.DB_PATH", test_db)
    init_database()
    yield test_db
    # Cleanup - ensure all connections are closed
    import gc
    gc.collect()
    try:
        if test_db.exists():
            test_db.unlink()
    except PermissionError:
        pass  # Windows file locking, will be cleaned up by tmp_path


@pytest.fixture
def sample_job():
    """Sample job listing."""
    return JobListing(
        id="greenhouse-123",
        title="Senior Software Engineer",
        company="TechCorp",
        url="https://greenhouse.io/job/123",
        platform="greenhouse",
    )


@pytest.fixture
def sample_profile():
    """Sample candidate profile."""
    return CandidateProfile(
        full_name="John Doe",
        email="john@example.com",
        phone="+1-555-0123",
        resume_path="/path/to/resume.pdf",
        linkedin_url="https://linkedin.com/in/johndoe",
    )


@pytest.fixture
def mock_greenhouse_api():
    """Mock Greenhouse API responses."""
    with patch("httpx.Client") as mock_client:
        mock_instance = Mock()
        mock_client.return_value.__enter__.return_value = mock_instance

        # Mock form definition fetch
        mock_instance.get.return_value.json.return_value = {
            "job": {
                "id": "greenhouse-123",
                "questions": [
                    {
                        "id": 1,
                        "type": "short_text",
                        "label": "First Name",
                        "required": True,
                    },
                    {
                        "id": 2,
                        "type": "short_text",
                        "label": "Last Name",
                        "required": True,
                    },
                    {
                        "id": 3,
                        "type": "email",
                        "label": "Email",
                        "required": True,
                    },
                ],
            }
        }

        # Mock submission response
        mock_instance.post.return_value.status_code = 200
        mock_instance.post.return_value.json.return_value = {
            "application_id": "app-456"
        }

        yield mock_instance


@pytest.fixture
def greenhouse_agent():
    """Greenhouse agent instance."""
    from src.agents.greenhouse_agent import GreenhouseAgent

    return GreenhouseAgent(board_token="test-board-token")
