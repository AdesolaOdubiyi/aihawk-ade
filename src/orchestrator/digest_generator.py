"""Generate a structured markdown email digest of discovered jobs."""

from typing import List, Dict, Optional
from datetime import datetime
from src.agents.base_agent import JobListing

BELOW_THRESHOLD_MARKER = "[BELOW THRESHOLD]"


def generate_digest(
    jobs: List[JobListing],
    salaries: Dict[str, Optional[float]],
    salary_floor: float = 40.0,
    batch_id: Optional[str] = None,
) -> str:
    """Generate a markdown digest email for the discovered jobs.

    Job titles, companies, and URLs originate from external job boards and are
    escaped before interpolation so a crafted posting cannot inject markdown
    links into the digest.
    """
    if not jobs:
        return "No jobs discovered."

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    digest = f"# Job Discovery Batch\n\n**Generated:** {timestamp}\n"

    if batch_id:
        digest += f"**Batch ID:** {_escape_markdown(batch_id)}\n"

    digest += f"**Total Jobs:** {len(jobs)}\n\n"
    digest += "---\n\n"

    for idx, job in enumerate(jobs, 1):
        salary = salaries.get(job.id)

        digest += f"## Job {idx}: {_escape_markdown(job.title)}\n\n"
        digest += f"- **Company:** {_escape_markdown(job.company)}\n"
        digest += f"- **Platform:** {_escape_markdown(job.platform.title())}\n"
        digest += _format_salary_line(salary, salary_floor)
        digest += _format_link_line(job.url)

    digest += "---\n\n"
    digest += "## Action\n\n"
    digest += "Reply with your approval:\n"
    digest += "```\n"
    digest += "APPROVE: 1, 3, 5\n"
    digest += "REJECT: 2, 4\n"
    digest += "```\n\n"
    digest += "Or: `APPROVE all` or `REJECT all`\n\n"
    digest += "Only approved jobs will be auto-applied.\n"

    return digest


def _format_salary_line(salary: Optional[float], salary_floor: float) -> str:
    """Render the salary bullet, flagging sub-threshold (and $0) values."""
    if salary is None:
        return "- **Salary:** Not specified\n"

    salary_str = f"${salary:.2f}/hr"
    if salary < salary_floor:
        salary_str += f" {BELOW_THRESHOLD_MARKER}"
    return f"- **Salary:** {salary_str}\n"


def _format_link_line(url: str) -> str:
    """Render the link bullet from a (possibly empty) URL."""
    if not url:
        return "- **Link:** Not provided\n\n"
    label = _escape_markdown(url.rstrip('/').split('/')[-1] or url)
    return f"- **Link:** [{label}]({url})\n\n"


def _escape_markdown(value: str) -> str:
    """Neutralize markdown control characters in externally sourced text."""
    text = str(value)
    for char in ('\\', '[', ']', '(', ')', '`', '*', '_', '#', '!', '<', '>'):
        text = text.replace(char, f'\\{char}')
    return text
