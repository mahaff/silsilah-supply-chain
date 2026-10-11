"""Labels for where a number or sentence came from.

Database facts and deterministic rules come from stored rows.
Predictions, investigation summaries, and human decisions use their own labels
so a report cannot present one of them as another.
"""

from enum import Enum


class EvidenceKind(str, Enum):
    DATABASE_FACT = "database_fact"
    DETERMINISTIC_RULE = "deterministic_rule"
    ML_PREDICTION = "ml_prediction"
    LLM_REASONING = "llm_reasoning"
    HUMAN_DECISION = "human_decision"
    INVESTIGATION_SUMMARY = "investigation_summary"


EVIDENCE_LABELS: dict[EvidenceKind, str] = {
    EvidenceKind.DATABASE_FACT: "Database fact",
    EvidenceKind.DETERMINISTIC_RULE: "Deterministic rule",
    EvidenceKind.ML_PREDICTION: "ML prediction",
    EvidenceKind.LLM_REASONING: "LLM reasoning",
    EvidenceKind.HUMAN_DECISION: "Human decision",
    EvidenceKind.INVESTIGATION_SUMMARY: "Investigation summary",
}


def evidence_label(kind: EvidenceKind) -> str:
    """Return the short label shown on screen for an evidence kind."""
    return EVIDENCE_LABELS[kind]
