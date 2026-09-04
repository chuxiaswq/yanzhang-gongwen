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
_DATE_ANCHOR = re.compile(
    r"(?:"
    r"(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])"
    r"|(?:19|20)\d{2}年(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日"
    r"|(?:19|20)\d{2}年(?:0?[1-9]|1[0-2])月"
    r"|(?:19|20)\d{2}年(?:上半年|下半年|第?[一二三四1234]季度|年初|年底)"
    r"|(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日"
    r"|(?:0?[1-9]|1[0-2])月底"
    r")"
)
_NUMBER_UNIT = (
    r"个百分点|万亿元|亿元|万元|平方公里|平方米|公里|千米|小时|分钟|"
    r"万人次|人次|万人|套|座|所|户|家|个|项|件|次|条|天|人|元|%|％"
)
_NUMBER = re.compile(rf"(?<![\d.])\d+(?:,\d{{3}})*(?:\.\d+)?(?:{_NUMBER_UNIT})?")
_CHINESE_NUMBER = re.compile(
    rf"[零〇一二两三四五六七八九十百千][零〇一二两三四五六七八九十百千万亿]*(?:{_NUMBER_UNIT})"
)
_QUOTATION = re.compile(r"[“\"]\S.{0,500}?[”\"]")
_QUOTATION_ANCHOR = re.compile(r"[“\"]([^”\"]{2,500})[”\"]")
_STRUCTURAL_QUOTATION_PREFIXES = ("围绕",)
_NON_CLAIM_BLOCKS = frozenset({"title", "subtitle", "heading", "references"})
_MAX_EVIDENCE_RELATIONS = 100_000
_FULL_WIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


@dataclass(frozen=True, slots=True)
class ProvenanceGraph:
    """A complete set of immutable provenance objects for one asset."""

    asset: TextAsset
    evidence: tuple[Evidence, ...]
    claims: tuple[Claim, ...]
    citations: tuple[Citation, ...]


def evidence_from_material(item: KnowledgeItem) -> Evidence:
    """Create the stable, bounded evidence record for one selected material."""

    if item.kind == "style_reference":
        raise ValueError("写法参考不得转换为事实证据")
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
    *,
    structural_topic: str | None = None,
) -> ProvenanceGraph:
    """Bind selected materials to blocks and derive traceable claims and citations."""

    factual_materials = tuple(item for item in materials if item.kind != "style_reference")
    blocks, evidence = attach_material_evidence(
        asset.blocks,
        factual_materials,
        structural_topic=structural_topic,
    )
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
    *,
    structural_topic: str | None = None,
) -> tuple[tuple[ContentBlock, ...], tuple[Evidence, ...]]:
    """Attach stable evidence IDs before the first asset revision is persisted."""

    factual_materials = tuple(item for item in materials if item.kind != "style_reference")
    evidence = tuple(evidence_from_material(item) for item in factual_materials)
    evidence_by_material = {item.knowledge_item_id: item for item in evidence}
    return (
        _attach_block_evidence(
            blocks,
            evidence_by_material,
            structural_topic=structural_topic,
        ),
        evidence,
    )


def supporting_evidence_for_text(
    text: str,
    evidence: Sequence[Evidence],
    *,
    structural_topic: str | None = None,
) -> tuple[Evidence, ...]:
    """Return evidence that conservatively covers every checkable anchor in ``text``.

    Source identifiers on a content block are candidate links rather than proof. A
    number, date, or direct quotation receives provenance only when the linked
    excerpts collectively contain every such anchor. Anchor-free prose retains its
    explicitly selected candidate links.
    """

    candidates = tuple(evidence)
    anchors_by_evidence = {item.id: checkable_fact_anchors(item.excerpt) for item in candidates}
    return _supporting_evidence(
        checkable_fact_anchors(text, structural_topic=structural_topic),
        candidates,
        anchors_by_evidence,
    )


def checkable_fact_anchors(
    text: str,
    *,
    structural_topic: str | None = None,
) -> frozenset[str]:
    """Extract normalized numbers, dates and direct quotations for source checks."""

    return frozenset(_factual_anchors(text, structural_topic=structural_topic))


def _supporting_evidence(
    required: frozenset[str],
    candidates: tuple[Evidence, ...],
    anchors_by_evidence: Mapping[str, frozenset[str]],
) -> tuple[Evidence, ...]:
    if not candidates:
        return ()
    if not required:
        return candidates
    available = frozenset().union(
        *(anchors_by_evidence.get(item.id, frozenset()) for item in candidates)
    )
    if not required.issubset(available):
        return ()
    return tuple(item for item in candidates if required.intersection(anchors_by_evidence[item.id]))


def _attach_block_evidence(
    blocks: Sequence[ContentBlock],
    evidence_by_material: Mapping[str, Evidence],
    *,
    structural_topic: str | None,
) -> tuple[ContentBlock, ...]:
    anchors_by_evidence = {
        item.id: checkable_fact_anchors(item.excerpt) for item in evidence_by_material.values()
    }
    linked: list[ContentBlock] = []
    for block in blocks:
        candidates = tuple(
            evidence_by_material[item_id]
            for item_id in block.knowledge_item_ids
            if item_id in evidence_by_material
        )
        supported = _supporting_evidence(
            checkable_fact_anchors(block.text, structural_topic=structural_topic),
            candidates,
            anchors_by_evidence,
        )
        linked.append(
            block.model_copy(update={"evidence_ids": tuple(item.id for item in supported)})
        )
    return tuple(linked)


def _factual_anchors(
    text: str,
    *,
    structural_topic: str | None,
) -> tuple[str, ...]:
    normalized_text = re.sub(r"\s+", "", text.translate(_FULL_WIDTH_DIGITS))
    anchors: list[str] = []
    date_spans: list[tuple[int, int]] = []
    for match in _DATE_ANCHOR.finditer(normalized_text):
        date_spans.append(match.span())
        anchors.append("date:" + _normalize_date_anchor(match.group()))
    for match in _NUMBER.finditer(normalized_text):
        if any(match.start() < end and match.end() > start for start, end in date_spans):
            continue
        if match.group().isdigit() and len(match.group()) == 1:
            continue
        anchors.append("number:" + _normalize_number_anchor(match.group()))
    anchors.extend(
        "number:" + _normalize_anchor(match.group())
        for match in _CHINESE_NUMBER.finditer(normalized_text)
    )
    anchors.extend(
        "quotation:" + _normalize_anchor(match.group(1))
        for match in _QUOTATION_ANCHOR.finditer(normalized_text)
        if not _is_structural_topic_quotation(
            normalized_text,
            match,
            structural_topic=structural_topic,
        )
    )
    return tuple(dict.fromkeys(anchor for anchor in anchors if anchor.rsplit(":", 1)[-1]))


def _is_structural_topic_quotation(
    normalized_text: str,
    match: re.Match[str],
    *,
    structural_topic: str | None,
) -> bool:
    if not structural_topic:
        return False
    return normalized_text[: match.start()].endswith(
        _STRUCTURAL_QUOTATION_PREFIXES
    ) and _normalize_anchor(match.group(1)) == _normalize_anchor(structural_topic)


def _normalize_number_anchor(value: str) -> str:
    return _normalize_anchor(value).replace(",", "").replace("％", "%")


def _normalize_date_anchor(value: str) -> str:
    normalized = _normalize_anchor(value)
    components = re.findall(
        r"\d+|上半年|下半年|第?[一二三四]季度|年初|年底|月底",
        normalized,
    )
    return "|".join(
        str(int(component)) if component.isdigit() else component for component in components
    )


def _normalize_anchor(value: str) -> str:
    return re.sub(r"\s+", "", value.translate(_FULL_WIDTH_DIGITS)).casefold()


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
    "checkable_fact_anchors",
    "evidence_from_material",
    "supporting_evidence_for_text",
]
