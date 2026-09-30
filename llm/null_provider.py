"""The only reasoning provider in MVP 1.

No network call is made. No API key is read. python-dotenv is loaded so a
later provider can use the same environment file without becoming required
for the app to start.
"""

from dotenv import load_dotenv

from domain.evidence import EvidenceKind
from llm.base import FactPacket, LLMProvider, ReasoningNote

NULL_NOTE = (
    "No language model is connected. "
    "These metrics were calculated in Python from the regional database. "
    "A model can be added later as an optional explanation layer. "
    "It will not replace these calculations."
)


class NullLLMProvider:
    """A provider that always says reasoning is unavailable."""

    name = "null"

    def explain(self, facts: FactPacket) -> ReasoningNote:
        # The packet is required so the future method signature is stable.
        # Its numbers are intentionally left out of the sentence.
        if not facts.region_code or not facts.supply_chain_id:
            raise ValueError("A fact packet needs a region and a supply chain.")
        return ReasoningNote(
            provider_name=self.name,
            available=False,
            text=NULL_NOTE,
            evidence_kind=EvidenceKind.LLM_REASONING,
        )


def get_provider() -> LLMProvider:
    """Return the MVP 1 provider.

    LLM_ENABLED and XAI_API_KEY are not consulted. Changing them does not
    turn on a model, because no model client is installed.
    """
    load_dotenv()
    return NullLLMProvider()
