"""Deterministic provenance relations for general writing assets.

This module is deliberately pure: it turns explicitly selected project materials
into bounded evidence records, attaches those records to content blocks, and
derives the Claim -> Citation -> Evidence graph that a repository can persist.
It never reads a database or contacts a provider.
"""

# Chinese fixture text and punctuation are intentional.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from yanzhang_core.models import (
    Citation,
    Claim,
    ClaimKind,
    ContentBlock,
    Evidence,
    KnowledgeItem,
    TextAsset,
)

_DATE = re.compile(r"(?:\d{4}[年/-]\d{1,2}(?:[月/-]\d{1,2}日?)?|\d{1,2}月\d{1,2}日)")
_NUMBER = re.compile(r"\d[\d,.]*(?:%|％)?")
_QUOTATION = re.compile(r"[“\"]\S.{0,500}?[”\"]")
_NON_CLAIM_BLOCKS = frozenset({"title", "subtitle", "heading", "references"})
_MAX_EVIDENCE_RELATIONS = 100_000


@dataclass(frozen=True, slots=True)
class ProvenanceGraph:
    """A complete set of immutable provenance objects for one asset."""

    asset: TextAsset
    evidence: tuple[Evidence, ...]
    claims: tuple[Claim, ...]
    citations: tuple[Citation, ...]


def evidence_from_material(item: KnowledgeItem) -> Evidence:
    """Create the stable, bounded evidence record for one selected material."""

    source_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
    return Evidence(
        id=_stable_id("evidence", item.id, source_hash),
        knowledge_item_id=item.id,
        excerpt=item.content[:8_000],
        locator="正文（截取前8000字符）" if len(item.content) > 8_000 else "正文全文",
        source_url=item.source_url,
        source_hash=source_hash,
        published_at=item.published_at,
    )


def build_provenance_graph(
    asset: TextAsset,
    materials: Sequence[KnowledgeItem],
) -> ProvenanceGraph:
    """Bind selected materials to blocks and derive traceable claims and citations."""

    blocks, evidence = attach_material_evidence(asset.blocks, materials)
    evidence_by_id = {item.id: item for item in evidence}
    linked_asset = asset.model_copy(update={"blocks": blocks})
    claims: list[Claim] = []
    citations: list[Citation] = []
    relation_count = 0
    for block in blocks:
        if block.kind in _NON_CLAIM_BLOCKS or not block.text.strip():
            continue
        claim = Claim(
            id=_stable_id("claim", asset.id, block.id, block.text),
            asset_id=asset.id,
            block_id=block.id,
            text=block.text[:8_000],
            kind=_claim_kind(block.text),
            status="supported" if block.evidence_ids else "unsupported",
            evidence_ids=block.evidence_ids,
            confidence=90 if block.evidence_ids else 0,
        )
        claims.append(claim)
        for evidence_id in block.evidence_ids:
            relation_count += 1
            if relation_count > _MAX_EVIDENCE_RELATIONS:
                raise ValueError("资产证据关系超过100000条上限")
            evidence_item = evidence_by_id[evidence_id]
            citations.append(
                Citation(
                    id=_stable_id("citation", asset.id, block.id, claim.id, evidence_id),
                    asset_id=asset.id,
                    block_id=block.id,
                    claim_id=claim.id,
                    evidence_id=evidence_id,
                    label=evidence_item.locator or evidence_item.knowledge_item_id,
                )
            )
    return ProvenanceGraph(
        asset=linked_asset,
        evidence=evidence,
        claims=tuple(claims),
        citations=tuple(citations),
    )


def attach_material_evidence(
    blocks: Sequence[ContentBlock],
    materials: Sequence[KnowledgeItem],
) -> tuple[tuple[ContentBlock, ...], tuple[Evidence, ...]]:
    """Attach stable evidence IDs before the first asset revision is persisted."""

    evidence = tuple(evidence_from_material(item) for item in materials)
    evidence_by_material = {item.knowledge_item_id: item for item in evidence}
    return _attach_block_evidence(blocks, evidence_by_material), evidence


def _attach_block_evidence(
    blocks: Sequence[ContentBlock],
    evidence_by_material: Mapping[str, Evidence],
) -> tuple[ContentBlock, ...]:
    return tuple(
        block.model_copy(
            update={
                "evidence_ids": tuple(
                    evidence_by_material[item_id].id
                    for item_id in block.knowledge_item_ids
                    if item_id in evidence_by_material
                )
            }
        )
        for block in blocks
    )


def _claim_kind(text: str) -> ClaimKind:
    if _DATE.search(text):
        return "date"
    if _NUMBER.search(text):
        return "number"
    if _QUOTATION.search(text):
        return "quotation"
    return "fact"


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}-{digest}"


__all__ = [
    "ProvenanceGraph",
    "attach_material_evidence",
    "build_provenance_graph",
    "evidence_from_material",
]
