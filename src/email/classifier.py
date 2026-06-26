import re
from enum import Enum
from dataclasses import dataclass
from loguru import logger


class EmailClassification(Enum):
    REJECTION = "rejection"
    INTERVIEW = "interview"
    ACTION_REQUIRED = "action_required"
    NOISE = "noise"


@dataclass
class ClassificationResult:
    classification: EmailClassification
    confidence: float
    reasoning: str


# Rejection patterns (score ≥ 7.5 = rejection)
REJECTION_PATTERNS = {
    r"unfortunately|regret|not moving forward|at this time|decided not to": 5,
    r"decided to move forward with another|other candidates|not selected": 8,
    r"position.*filled|not fit our needs": 6,
    r"appreciated but|we appreciate|thanks.*but": 5,
    r"unsuccessful|not successful|didn't select": 7,
}

# Interview patterns (score ≥ 7.0 = interview)
INTERVIEW_PATTERNS = {
    r"(calendly|doodle|calendar|scheduling link)": 10,
    r"phone screen|phone call|phone interview": 7,
    r"video call|video interview|zoom|teams|skype": 7,
    r"next step|move.*forward|interview|speak": 6,
    r"schedule.*interview|interview scheduled|let.s discuss": 8,
    r"\d{1,2}[/\-]\d{1,2}|\d{1,2}\s*(am|pm)|wednesday|thursday|friday": 8,
}

# Action required patterns (score ≥ 7.0 = action_required)
ACTION_PATTERNS = {
    r"background check.*by|background check.*deadline|background check.*within": 9,
    r"submit.*by.*\d|provide.*document|upload": 10,
    r"assessment.*within|complete.*assessment|quiz": 8,
    r"verify.*email|confirm.*email|click.*link": 7,
    r"reference.*check|reference.*required": 6,
    r"please complete|please provide|action required|complete.*by": 9,
}


def classify_email(subject: str, body: str) -> ClassificationResult:
    """Classify email as rejection, interview, action_required, or noise."""
    text = f"{subject} {body}".lower()

    rejection_score = _score_patterns(text, REJECTION_PATTERNS)
    interview_score = _score_patterns(text, INTERVIEW_PATTERNS)
    action_score = _score_patterns(text, ACTION_PATTERNS)

    # Determine classification and confidence
    max_score = max(rejection_score, interview_score, action_score)

    if rejection_score >= 7.5 and rejection_score == max_score:
        confidence = min(1.0, rejection_score / 10.0)
        return ClassificationResult(
            classification=EmailClassification.REJECTION,
            confidence=confidence,
            reasoning=f"Rejection patterns detected (score: {rejection_score:.1f})",
        )

    if interview_score >= 7.0 and interview_score == max_score:
        confidence = min(1.0, interview_score / 10.0)
        return ClassificationResult(
            classification=EmailClassification.INTERVIEW,
            confidence=confidence,
            reasoning=f"Interview invitation patterns detected (score: {interview_score:.1f})",
        )

    if action_score >= 7.0 and action_score == max_score:
        confidence = min(1.0, action_score / 10.0)
        return ClassificationResult(
            classification=EmailClassification.ACTION_REQUIRED,
            confidence=confidence,
            reasoning=f"Action required patterns detected (score: {action_score:.1f})",
        )

    # Ambiguous or no clear pattern
    confidence = max_score / 10.0
    return ClassificationResult(
        classification=EmailClassification.NOISE,
        confidence=confidence,
        reasoning=f"No clear pattern detected (max score: {max_score:.1f})",
    )


def _score_patterns(text: str, patterns: dict) -> float:
    """Score text against pattern dictionary."""
    score = 0.0
    for pattern, weight in patterns.items():
        if re.search(pattern, text, re.IGNORECASE):
            score += weight

    return score
