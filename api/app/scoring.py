import math

DIMENSIONS = {
    "technical_skills": "Technical skills",
    "experience": "Relevant experience",
    "qualifications": "Qualifications",
    "jd_match": "Job description match",
}


def aggregate(scores: dict, weights: dict) -> float:
    """The weighted average of the four scores, 0-100, rounded half up to one decimal (77.75 -> 77.8)."""
    total_weight = sum(weights[d] for d in DIMENSIONS)
    average = sum(scores[d] * weights[d] for d in DIMENSIONS) / total_weight
    return math.floor(average * 10 + 0.5) / 10