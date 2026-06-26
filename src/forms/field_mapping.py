import re
import yaml
from pathlib import Path
from loguru import logger
from typing import Dict, List, Optional


FIELD_MAPPING_PATH = Path("data_folder") / "field_mapping.yaml"


def load_field_mapping() -> Dict[str, List[str]]:
    """Load field name variants from YAML config."""
    if FIELD_MAPPING_PATH.exists():
        try:
            with open(FIELD_MAPPING_PATH, "r") as f:
                config = yaml.safe_load(f)
                if config and "fields" in config:
                    logger.info(f"Loaded field mapping from {FIELD_MAPPING_PATH}")
                    return config["fields"]
                else:
                    logger.warning(f"Invalid field mapping format at {FIELD_MAPPING_PATH}")
        except Exception as e:
            logger.error(f"Failed to load field mapping: {e}")
    else:
        logger.warning(f"Field mapping not found at {FIELD_MAPPING_PATH}, using defaults")

    return _default_field_mapping()


def _default_field_mapping() -> Dict[str, List[str]]:
    """Default field name mapping."""
    return {
        "full_name": ["full_name", "fullName", "full name", "name", "applicant_name"],
        "first_name": ["first_name", "firstName", "first name", "given_name"],
        "last_name": ["last_name", "lastName", "last name", "family_name", "surname"],
        "email": ["email", "email_address", "emailAddress", "email_addr"],
        "phone": ["phone", "phone_number", "phoneNumber", "mobile", "mobile_phone"],
        "resume": [
            "resume",
            "cv",
            "resume_upload",
            "resume_file",
            "curriculum_vitae",
        ],
        "linkedin_url": [
            "linkedin",
            "linkedin_url",
            "linkedinUrl",
            "linkedin_profile",
            "linkedin_profile_url",
        ],
        "cover_letter": [
            "cover_letter",
            "coverLetter",
            "cover_letter_text",
            "cover_letter_file",
        ],
    }


def find_field_variant(field_label: str, field_mapping: Dict) -> Optional[str]:
    """Find the canonical field name for a label using the mapping.

    Handles both mapping shapes — the YAML's `{canonical: {variants: [...]}}` and
    the flat `{canonical: [variants]}` default — and normalizes separators so
    `first_name`, `first-name`, and `first name` all match the same variant.
    """
    target = normalize_label(field_label)

    # 1. Exact match wins — handles short labels ("Email", "Phone") cleanly.
    for canonical_name, spec in field_mapping.items():
        for variant in _variants_of(spec):
            if normalize_label(variant) == target:
                return canonical_name

    # 2. Otherwise, the longest multi-word variant that appears as a whole phrase
    #    inside the label. Real labels carry extra words ("Are you authorized to
    #    work in the US?"); multi-word-only avoids "name" matching "company name".
    best_canonical = None
    best_length = 0
    for canonical_name, spec in field_mapping.items():
        for variant in _variants_of(spec):
            normalized = normalize_label(variant)
            if " " not in normalized or len(normalized) <= best_length:
                continue
            if re.search(rf"\b{re.escape(normalized)}\b", target):
                best_canonical = canonical_name
                best_length = len(normalized)

    return best_canonical


def normalize_label(label: str) -> str:
    """Lowercase and collapse any run of non-alphanumerics to a single space.

    Makes `first_name`, `first-name`, "First Name", and "Race/Ethnicity?" all
    normalize to a comparable form, so form labels match mapping variants
    regardless of punctuation or separators.
    """
    return re.sub(r"[^a-z0-9]+", " ", (label or "").lower()).strip()


def _variants_of(spec) -> List[str]:
    """Extract the variant list from either mapping shape."""
    if isinstance(spec, dict):
        return spec.get("variants", [])
    if isinstance(spec, list):
        return spec
    return []
