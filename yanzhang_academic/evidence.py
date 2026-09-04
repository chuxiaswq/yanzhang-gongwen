"""Deterministic evidence extraction and literature-matrix construction."""

# ruff: noqa: RUF001 -- Chinese source punctuation is intentional.

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from yanzhang_academic.models import (
    BibliographicRecord,
    EvidenceKind,
    EvidenceSnippet,
    LiteratureMatrix,
    LiteratureMatrixRow,
)

_METHOD_TERMS = (
    "方法",
    "样本",
    "访谈",
    "问卷",
    "实验",
    "模型",
    "回归",
    "case study",
    "method",
    "sample",
    "survey",
    "experiment",
)
_FINDING_TERMS = (
    "发现",
    "结果",
    "表明",
    "显示",
    "证明",
    "研究认为",
    "find",
    "result",
    "show",
    "demonstrate",
)
_LIMITATION_TERMS = (
    "局限",
    "不足",
    "限制",
    "未来研究",
    "有待",
    "limitation",
    "future research",
)
_DEFINITION_TERMS = ("定义", "是指", "概念", "defined as", "refers to")
_BACKGROUND_TERMS = ("背景", "近年来", "现有研究", "已有研究", "background", "previous studies")


def tokenize_for_support(value: str) -> set[str]:
    """Build English word and Chinese bigram features for transparent scoring."""

    normalized = value.casefold()
    latin = set(re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*", normalized))
    chinese_runs = re.findall(r"[\u3400-\u9fff]+", normalized)
    chinese: set[str] = set()
    for run in chinese_runs:
        if len(run) == 1:
            chinese.add(run)
        else:
            chinese.update(run[index : index + 2] for index in range(len(run) - 1))
    return latin | chinese


def support_score(claim_text: str, evidence_text: str) -> float:
    """Return a bounded lexical-support indicator for human review prioritization."""

    claim_tokens = tokenize_for_support(claim_text)
    evidence_tokens = tokenize_for_support(evidence_text)
    if not claim_tokens or not evidence_tokens:
        return 0.0
    containment = len(claim_tokens & evidence_tokens) / len(claim_tokens)
    union = len(claim_tokens | evidence_tokens)
    jaccard = len(claim_tokens & evidence_tokens) / union if union else 0.0
    score = 0.75 * containment + 0.25 * jaccard
    return round(min(1.0, max(0.0, score)), 4)


def classify_evidence(text: str) -> EvidenceKind:
    """Classify one excerpt with explicit, inspectable keyword rules."""

    normalized = text.casefold()
    groups: tuple[tuple[EvidenceKind, tuple[str, ...]], ...] = (
        ("limitation", _LIMITATION_TERMS),
        ("method", _METHOD_TERMS),
        ("finding", _FINDING_TERMS),
        ("definition", _DEFINITION_TERMS),
        ("background", _BACKGROUND_TERMS),
    )
    for kind, terms in groups:
        if any(term in normalized for term in terms):
            return kind
    return "other"


def extract_evidence(
    record: BibliographicRecord,
    source_text: str,
    *,
    query: str = "",
    max_snippets: int = 20,
    min_characters: int = 12,
) -> list[EvidenceSnippet]:
    """Extract bounded, source-hash-bound sentence or paragraph excerpts."""

    if max_snippets < 1 or max_snippets > 100:
        raise ValueError("max_snippets 必须在 1 到 100 之间")
    if min_characters < 1 or min_characters > 1_000:
        raise ValueError("min_characters 必须在 1 到 1000 之间")
    if len(source_text) > 5_000_000:
        raise ValueError("单份证据源文本不得超过 500 万字符")
    query_tokens = tokenize_for_support(query)
    candidates: list[tuple[float, int, EvidenceSnippet]] = []
    global_offset = 0
    paragraph_index = 0
    pages = source_text.split("\f")
    for page_number, page in enumerate(pages, start=1):
        for raw_paragraph in re.split(r"\n\s*\n|\r?\n", page):
            paragraph = " ".join(raw_paragraph.split())
            raw_start = source_text.find(raw_paragraph, global_offset)
            if raw_start < 0:
                raw_start = global_offset
            global_offset = raw_start + len(raw_paragraph)
            if not paragraph:
                continue
            paragraph_index += 1
            segments = _segments(paragraph)
            if not segments:
                segments = [paragraph]
            for segment in segments:
                if len(segment) < min_characters:
                    continue
                local_start = paragraph.find(segment)
                start = raw_start + max(0, local_start)
                kind = classify_evidence(segment)
                score = _query_score(query_tokens, tokenize_for_support(segment), kind)
                snippet = EvidenceSnippet(
                    record_id=record.id,
                    record_source_hash=record.source_hash,
                    text=segment,
                    kind=kind,
                    page_start=page_number if len(pages) > 1 else None,
                    page_end=page_number if len(pages) > 1 else None,
                    paragraph_index=paragraph_index,
                    char_start=start,
                    char_end=start + len(segment),
                )
                candidates.append((score, start, snippet))
    if query_tokens:
        candidates = [candidate for candidate in candidates if candidate[0] > 0]
        candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    else:
        candidates.sort(key=lambda candidate: candidate[1])
    return [candidate[2] for candidate in candidates[:max_snippets]]


def _segments(paragraph: str) -> list[str]:
    if len(paragraph) <= 500:
        return [paragraph]
    return [
        segment.strip()
        for segment in re.split(r"(?<=[。！？!?；;])\s*|(?<=[.!?])\s+", paragraph)
        if segment.strip()
    ]


def _query_score(query_tokens: set[str], excerpt_tokens: set[str], kind: EvidenceKind) -> float:
    if not query_tokens:
        return 1.0 if kind != "other" else 0.5
    if not excerpt_tokens:
        return 0.0
    overlap = len(query_tokens & excerpt_tokens) / len(query_tokens)
    return overlap + (0.05 if kind != "other" and overlap else 0.0)


def build_literature_matrix(
    records: Sequence[BibliographicRecord],
    evidence: Sequence[EvidenceSnippet] = (),
    *,
    query: str = "",
) -> LiteratureMatrix:
    """Build a matrix using only evidence tied to the supplied imported records."""

    record_map = _unique_records(records)
    by_record: dict[str, list[EvidenceSnippet]] = {record_id: [] for record_id in record_map}
    for snippet in evidence:
        record = record_map.get(snippet.record_id)
        if record is None or snippet.record_source_hash != record.source_hash:
            continue
        by_record[record.id].append(snippet)

    rows: list[LiteratureMatrixRow] = []
    theme_counts: Counter[str] = Counter()
    for record in records:
        snippets = by_record[record.id]
        themes = list(dict.fromkeys(record.keywords))[:10]
        theme_counts.update(themes)
        object_text = _first_sentence(record.abstract)
        rows.append(
            LiteratureMatrixRow(
                record_id=record.id,
                citation_label=_citation_label(record),
                research_object=object_text,
                methods=_kind_texts(snippets, "method"),
                findings=_kind_texts(snippets, "finding"),
                limitations=_kind_texts(snippets, "limitation"),
                themes=themes,
                evidence_ids=[snippet.id for snippet in snippets],
            )
        )
    themes = [theme for theme, _ in theme_counts.most_common(20)]
    return LiteratureMatrix(
        query=" ".join(query.split()),
        rows=rows,
        themes=themes,
        record_ids=list(record_map),
    )


def _unique_records(records: Sequence[BibliographicRecord]) -> dict[str, BibliographicRecord]:
    result: dict[str, BibliographicRecord] = {}
    for record in records:
        if record.id in result:
            raise ValueError(f"文献记录 ID 重复：{record.id}")
        result[record.id] = record
    return result


def _kind_texts(snippets: Sequence[EvidenceSnippet], kind: EvidenceKind) -> list[str]:
    return [snippet.text for snippet in snippets if snippet.kind == kind][:5]


def _first_sentence(value: str) -> str:
    if not value:
        return ""
    return re.split(r"(?<=[。！？!?])\s*|(?<=[.!?])\s+", value, maxsplit=1)[0][:500]


def _citation_label(record: BibliographicRecord) -> str:
    if record.authors:
        author = record.authors[0].display_name(family_first=True)
        if len(record.authors) > 1:
            author = f"{author} 等"
    else:
        author = "佚名"
    return f"{author}（{record.issued_year or '日期不详'}）"


__all__ = [
    "build_literature_matrix",
    "classify_evidence",
    "extract_evidence",
    "support_score",
    "tokenize_for_support",
]
