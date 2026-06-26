"""Generate structured markdown email digest of discovered jobs."""

from typing import List, Dict, Optional
from datetime import datetime
from src.agents.base_agent import JobListing


def generate_digest(
    jobs: List[JobListing],
    salaries: Dict[str, Optional[float]],
    salary_floor: float = 40.0,
    batch_id: Optional[str] = None,
) -> str:
    """Generate markdown digest email."""
    if not jobs:
        return "No jobs discovered."

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    digest = f"# Job Discovery Batch\n\n**Generated:** {timestamp}\n"

    if batch_id:
        digest += f"**Batch ID:** {batch_id}\n"

    digest += f"**Total Jobs:** {len(jobs)}\n\n"
    digest += "---\n\n"

    for idx, job in enumerate(jobs, 1):
        salary = salaries.get(job.id)
        below_floor = salary and salary < salary_floor

        digest += f"## Job {idx}: {job.title}\n\n"
        digest += f"- **Company:** {job.company}\n"
        digest += f"- **Platform:** {job.platform.title()}\n"

        if salary:
            salary_str = f"${salary:.2f}/hr"
            if below_floor:
                salary_str += " ⚠️ Below threshold"
            digest += f"- **Salary:** {salary_str}\n"
        else:
            digest += f"- **Salary:** Not specified\n"

        digest += f"- **Link:** [{job.url.split('/')[-1]}]({job.url})\n\n"

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
