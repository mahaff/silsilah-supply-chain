"""The seam a future language-model provider must implement.

Callers pass numbers that Python has already calculated. A provider may
return a sentence about those facts. It is not given a way to change them.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from domain.evidence import EvidenceKind
from domain.metrics import Metric


class FactPacket(BaseModel):
    """A bundle of finished metrics. This is input to a reasoning note."""

    model_config = ConfigDict(extra="forbid")

    region_code: str
    supply_chain_id: str
    metrics: list[Metric]


class ReasoningNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_name: str
    available: bool
    text: str
    evidence_kind: EvidenceKind


class LLMProvider(Protocol):
    """Explain a fact packet. Implementations must not recalculate metrics."""

    name: str

    def explain(self, facts: FactPacket) -> ReasoningNote:
        """Return a note. The null provider returns a fixed unavailable note."""
