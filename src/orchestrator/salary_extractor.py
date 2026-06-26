"""Extract and normalize salary from job descriptions."""

import re
from typing import Optional
from loguru import logger


def extract_salary(description: str) -> Optional[float]:
    """Extract salary from job description, normalize to hourly rate.

    Returns hourly rate or None if not found.
    Tries: hourly → annual range → annual single → fallback None
    """
    if not description:
        return None

    description_lower = description.lower()

    # 1. Try hourly rate: "$50/hr", "$50 per hour", "$50/hour"
    hourly_match = re.search(
        r'\$(\d+(?:[.,]\d{2})?)\s*(?:/\s*)?(?:hr|hour|per\s*hour)',
        description,
        re.IGNORECASE
    )
    if hourly_match:
        try:
            hourly = float(hourly_match.group(1).replace(",", ""))
            logger.debug(f"Extracted hourly salary: ${hourly}/hr")
            return hourly
        except ValueError:
            pass

    # 2. Try annual range: "$45K - $55K", "$45,000 - $55,000"
    range_match = re.search(
        r'\$(\d+(?:[.,]\d{3})*)[kK]?\s*[-–—]\s*\$(\d+(?:[.,]\d{3})*)[kK]?',
        description
    )
    if range_match:
        try:
            low = float(range_match.group(1).replace(",", ""))
            high = float(range_match.group(2).replace(",", ""))

            # If values < 1000, assume they're already in K
            if low < 1000:
                low *= 1000
            if high < 1000:
                high *= 1000

            avg = (low + high) / 2
            hourly = avg / 2080  # annual to hourly
            logger.debug(f"Extracted salary range ${low}-${high}/yr → ${hourly:.2f}/hr")
            return hourly
        except ValueError:
            pass

    # 3. Try single annual: "$75,000/year", "$75K/year", "$75K annually"
    annual_match = re.search(
        r'\$(\d+(?:[.,]\d{3})*)[kK]?\s*(?:/\s*)?(?:year|annually|per\s*year)',
        description,
        re.IGNORECASE
    )
    if annual_match:
        try:
            annual = float(annual_match.group(1).replace(",", ""))

            # If < 1000, assume K
            if annual < 1000:
                annual *= 1000

            hourly = annual / 2080
            logger.debug(f"Extracted annual salary ${annual}/yr → ${hourly:.2f}/hr")
            return hourly
        except ValueError:
            pass

    # 4. Try "$50K" (no unit): assume hourly if < 100, annual if >= 100
    amount_match = re.search(r'\$(\d+)[kK]\b', description)
    if amount_match:
        try:
            amount = int(amount_match.group(1))
            if amount < 100:
                # Assume hourly
                logger.debug(f"Extracted amount ${amount}K (assumed hourly) → ${amount:.2f}/hr")
                return float(amount)
            else:
                # Assume annual
                annual = amount * 1000
                hourly = annual / 2080
                logger.debug(f"Extracted amount ${amount}K (assumed annual) → ${hourly:.2f}/hr")
                return hourly
        except ValueError:
            pass

    logger.debug(f"No salary found in description")
    return None


def normalize_to_hourly(salary: float, unit: str) -> float:
    """Normalize salary to hourly rate."""
    if unit.lower() in ["hr", "hour", "hourly"]:
        return salary
    elif unit.lower() in ["year", "annual"]:
        return salary / 2080  # ~2080 work hours/year
    else:
        return salary


def meets_floor(salary: Optional[float], floor: float) -> bool:
    """Check if salary meets minimum floor."""
    if salary is None:
        return True  # Unknown salary passes (user can filter manually)
    return salary >= floor
