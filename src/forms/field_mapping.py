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
    """Find canonical field name for a label using the mapping."""
    field_label_lower = field_label.lower().strip()

    for canonical_name, variants in field_mapping.items():
        for variant in variants:
            if variant.lower() == field_label_lower:
                return canonical_name

    return None
