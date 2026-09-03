"""Central resource budgets for CPU-heavy personal-writing operations.

The web request-size limit bounds bytes on the wire.  These budgets additionally
bound the amount of structured work created from a compact request, such as one
large template expanded across many batch rows.
"""

from __future__ import annotations

from typing import Final

# ArticleLibrary currently combines page acquisition and persistence.  Collection
# therefore applies these deadlines around each ordered side-effecting import.
ARTICLE_COLLECTION_DISCOVERY_TIMEOUT_SECONDS: Final = 20.0
ARTICLE_COLLECTION_ITEM_TIMEOUT_SECONDS: Final = 25.0
ARTICLE_COLLECTION_BATCH_TIMEOUT_SECONDS: Final = 90.0
ARTICLE_COLLECTION_MAX_DISCOVERY_TIMEOUT_SECONDS: Final = 60.0
ARTICLE_COLLECTION_MAX_ITEM_TIMEOUT_SECONDS: Final = 120.0
ARTICLE_COLLECTION_MAX_BATCH_TIMEOUT_SECONDS: Final = 600.0

# Fact-audit input limits.  They are intentionally lower than the generic document
# storage limit because the audit performs cross-comparisons between claims and facts.
MAX_FACT_AUDIT_CONTENT_CHARACTERS: Final = 30_000
MAX_FACT_AUDIT_TITLE_CHARACTERS: Final = 300
MAX_FACT_AUDIT_MATERIAL_ITEMS: Final = 16
MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS: Final = 25_000
MAX_FACT_AUDIT_MATERIAL_CHARACTERS: Final = 50_000
MAX_FACT_AUDIT_TOTAL_CHARACTERS: Final = 60_000

# Derived-work limits keep both runtime and JSON response size predictable.
MAX_FACT_AUDIT_SENTENCES: Final = 600
MAX_FACT_AUDIT_MATERIAL_SENTENCES: Final = 1_000
MAX_FACT_AUDIT_FACTS: Final = 600
MAX_FACT_AUDIT_CLAIMS: Final = 600
MAX_FACT_AUDIT_MENTIONS_PER_SENTENCE: Final = 32
MAX_FACT_AUDIT_SENTENCE_CHARACTERS: Final = 2_000
MAX_FACT_AUDIT_CONTEXT_CHARACTERS: Final = 240
MAX_FACT_AUDIT_COMPARISONS: Final = 40_000

# Expanded characters are counted after mail-merge substitution.  This prevents a
# small template plus many rows from multiplying into an unexpectedly large archive.
MAX_BATCH_EXPANDED_CHARACTERS: Final = 5_000_000


__all__ = [
    "ARTICLE_COLLECTION_BATCH_TIMEOUT_SECONDS",
    "ARTICLE_COLLECTION_DISCOVERY_TIMEOUT_SECONDS",
    "ARTICLE_COLLECTION_ITEM_TIMEOUT_SECONDS",
    "ARTICLE_COLLECTION_MAX_BATCH_TIMEOUT_SECONDS",
    "ARTICLE_COLLECTION_MAX_DISCOVERY_TIMEOUT_SECONDS",
    "ARTICLE_COLLECTION_MAX_ITEM_TIMEOUT_SECONDS",
    "MAX_BATCH_EXPANDED_CHARACTERS",
    "MAX_FACT_AUDIT_CLAIMS",
    "MAX_FACT_AUDIT_COMPARISONS",
    "MAX_FACT_AUDIT_CONTENT_CHARACTERS",
    "MAX_FACT_AUDIT_CONTEXT_CHARACTERS",
    "MAX_FACT_AUDIT_FACTS",
    "MAX_FACT_AUDIT_MATERIAL_CHARACTERS",
    "MAX_FACT_AUDIT_MATERIAL_ITEMS",
    "MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS",
    "MAX_FACT_AUDIT_MATERIAL_SENTENCES",
    "MAX_FACT_AUDIT_MENTIONS_PER_SENTENCE",
    "MAX_FACT_AUDIT_SENTENCES",
    "MAX_FACT_AUDIT_SENTENCE_CHARACTERS",
    "MAX_FACT_AUDIT_TITLE_CHARACTERS",
    "MAX_FACT_AUDIT_TOTAL_CHARACTERS",
]
