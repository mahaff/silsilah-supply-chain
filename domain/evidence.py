"""Labels for where a number or sentence came from.

MVP 1 only produces database facts and deterministic rules.
The other labels exist so later phases can add predictions, model notes,
and human decisions without renaming this idea.
"""

from enum import Enum


class EvidenceKind(str, Enum):
    DATABASE_FACT = "database_fact"
    DETERMINISTIC_RULE = "deterministic_rule"
    ML_PREDICTION = "ml_prediction"
    LLM_REASONING = "llm_reasoning"
    HUMAN_DECISION = "human_decision"


EVIDENCE_LABELS: dict[EvidenceKind, str] = {
    EvidenceKind.DATABASE_FACT: "Database fact",
    EvidenceKind.DETERMINISTIC_RULE: "Deterministic rule",
    EvidenceKind.ML_PREDICTION: "ML prediction",
    EvidenceKind.LLM_REASONING: "LLM reasoning",
    EvidenceKind.HUMAN_DECISION: "Human decision",
}


def evidence_label(kind: EvidenceKind) -> str:
    """Return the short label shown on screen for an evidence kind."""
    return EVIDENCE_LABELS[kind]
