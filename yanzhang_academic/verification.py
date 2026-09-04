"""Citation-lineage and research-integrity checks for academic drafts."""

# ruff: noqa: RUF001 -- Chinese user-facing messages use full-width punctuation.

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol

from yanzhang_academic.evidence import support_score
from yanzhang_academic.models import (
    BibliographicRecord,
    CitationAudit,
    ClaimCitationLink,
    EvidenceSnippet,
    IntegrityReview,
    JournalProfile,
    ResearchClaim,
    ReviewComment,
)

_CJK_OR_WORD = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|"
    r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*"
)
_HEADING_PREFIX = re.compile(
    r"^(?:"
    r"#{1,6}\s*|"
    r"第[一二三四五六七八九十百千万0-9]+[章节篇部分]\s*[、.．:]?\s*|"
    r"[（(][一二三四五六七八九十百千万0-9]+[）)]\s*|"
    r"[一二三四五六七八九十百千万]+[、.．]\s*|"
    r"\d+(?:\.\d+)+[、.．]?\s*|"
    r"\d+[、.．]\s*|"
    r"\d+\s+"
    r")"
)
_ABSTRACT_LINE = re.compile(
    r"^(?:#{1,6}\s*)?(?:摘\s*要|abstract)(?:(?:\s*[:：]\s*)(.*))?$",
    re.IGNORECASE,
)
_KEYWORDS_LINE = re.compile(
    r"^(?:#{1,6}\s*)?(?:关\s*键\s*词|key\s*words?)(?:(?:\s*[:：]\s*)|$)",
    re.IGNORECASE,
)
_COMMON_SECTION_HEADINGS = frozenset(
    {
        "引言",
        "绪论",
        "研究背景",
        "文献综述",
        "研究方法",
        "材料与方法",
        "研究结果",
        "结果",
        "讨论",
        "结论",
        "参考文献",
        "introduction",
        "literaturereview",
        "methods",
        "materialsandmethods",
        "results",
        "discussion",
        "conclusion",
        "references",
    }
)


def verify_claim_citations(
    records: Sequence[BibliographicRecord],
    evidence: Sequence[EvidenceSnippet],
    claims: Sequence[ResearchClaim],
    links: Sequence[ClaimCitationLink],
    *,
    minimum_support_score: float = 0.18,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CitationAudit:
    """Validate IDs, source hashes and lexical support for every citation link."""

    if not 0.0 <= minimum_support_score <= 1.0:
        raise ValueError("minimum_support_score 必须在 0 到 1 之间")
    record_map = _unique(records, "文献")
    evidence_map = _unique(evidence, "证据")
    claim_map = _unique(claims, "论断")
    checked_links: list[ClaimCitationLink] = []
    comments: list[ReviewComment] = []
    seen_pairs: set[tuple[str, str]] = set()

    for link in links:
        issues: list[str] = []
        claim = claim_map.get(link.claim_id)
        record = record_map.get(link.record_id)
        snippet = evidence_map.get(link.evidence_id)
        if claim is None:
            issues.append("引用关联了未导入的论断")
        if record is None:
            issues.append("引用关联了未导入的文献记录")
        if snippet is None:
            issues.append("引用关联了不存在的证据片段")
        if record is not None and snippet is not None:
            if snippet.record_id != record.id:
                issues.append("证据片段与文献记录 ID 不一致")
            if snippet.record_source_hash != record.source_hash:
                issues.append("证据来源哈希与导入记录不一致")
        pair = (link.claim_id, link.evidence_id)
        if pair in seen_pairs:
            issues.append("论断与证据链接重复")
        seen_pairs.add(pair)

        score = support_score(claim.text, snippet.text) if claim is not None and snippet else 0.0
        if not issues and score < minimum_support_score:
            issues.append("证据与论断的词汇支持度较低，需核对原文语义")
            status = "needs-review"
        elif issues:
            status = "invalid"
        else:
            status = "verified"
        checked = link.model_copy(
            update={
                "support_score": score,
                "status": status,
                "issues": issues,
                "verified_at": clock() if status == "verified" else None,
            }
        )
        checked_links.append(checked)
        if status != "verified":
            comments.append(
                ReviewComment(
                    category="citation",
                    severity="error" if status == "invalid" else "warning",
                    message="；".join(issues),
                    recommendation="打开对应证据片段核对题录、页码和原文语义。",
                    claim_id=link.claim_id,
                    record_id=link.record_id,
                    evidence_id=link.evidence_id,
                )
            )

    required_claims = [claim for claim in claims if claim.requires_citation]
    supported_ids = {
        link.claim_id
        for link in checked_links
        if link.status == "verified" and link.relation == "supports"
    }
    for claim in required_claims:
        if claim.id not in supported_ids:
            comments.append(
                ReviewComment(
                    category="citation",
                    severity="error",
                    message="需要引用的论断尚未获得已核验的证据支持。",
                    recommendation="从已导入文献中选择原文片段并建立论断—证据链接。",
                    location=claim.section,
                    claim_id=claim.id,
                )
            )
    required_count = len(required_claims)
    supported_count = sum(claim.id in supported_ids for claim in required_claims)
    coverage = supported_count / required_count if required_count else 1.0
    return CitationAudit(
        links=checked_links,
        comments=_deduplicate_comments(comments),
        required_claim_count=required_count,
        supported_claim_count=supported_count,
        coverage=round(coverage, 4),
    )


def review_research_integrity(
    records: Sequence[BibliographicRecord],
    evidence: Sequence[EvidenceSnippet],
    claims: Sequence[ResearchClaim],
    links: Sequence[ClaimCitationLink],
    *,
    minimum_support_score: float = 0.18,
    manuscript: str | None = None,
    journal: JournalProfile | None = None,
) -> IntegrityReview:
    """Review source lineage plus optional manuscript and journal conformance.

    ``manuscript`` and ``journal`` are keyword-only so existing callers retain the
    original citation-only behavior.  Journal checks are deterministic shape checks;
    free-form journal rules are emitted as explicit human-review items rather than
    being reported as satisfied.
    """

    audit = verify_claim_citations(
        records,
        evidence,
        claims,
        links,
        minimum_support_score=minimum_support_score,
    )
    comments = list(audit.comments)
    doi_records: dict[str, str] = {}
    evidence_map = {snippet.id: snippet for snippet in evidence}
    verified_links_by_claim: dict[str, list[ClaimCitationLink]] = {}
    for link in audit.links:
        if link.status == "verified":
            verified_links_by_claim.setdefault(link.claim_id, []).append(link)

    for record in records:
        missing = []
        if not record.authors:
            missing.append("作者")
        if record.issued_year is None:
            missing.append("年份")
        if record.type == "article-journal" and not record.container_title:
            missing.append("刊名")
        if missing:
            comments.append(
                ReviewComment(
                    category="metadata",
                    severity="warning",
                    message=f"文献《{record.title}》缺少{'、'.join(missing)}。",
                    recommendation="回到原始文献或元数据服务补齐后重新核验。",
                    record_id=record.id,
                )
            )
        if record.doi:
            prior = doi_records.get(record.doi)
            if prior is not None and prior != record.id:
                comments.append(
                    ReviewComment(
                        category="metadata",
                        severity="warning",
                        message=f"DOI {record.doi} 对应了多条导入记录。",
                        recommendation="合并重复文献并保留一条权威题录。",
                        record_id=record.id,
                    )
                )
            doi_records[record.doi] = record.id
        if not record.metadata_verified:
            comments.append(
                ReviewComment(
                    category="metadata",
                    severity="info",
                    message=f"文献《{record.title}》来自本地导入，题录状态为待交叉核验。",
                    recommendation="使用 DOI、出版机构页面或元数据连接器核对题录。",
                    record_id=record.id,
                )
            )

    for claim in claims:
        claim_links = verified_links_by_claim.get(claim.id, [])
        linked_evidence = [
            evidence_map[link.evidence_id]
            for link in claim_links
            if link.evidence_id in evidence_map
        ]
        if _contains_direct_quote(claim.text) and linked_evidence:
            if all(snippet.page_start is None for snippet in linked_evidence):
                comments.append(
                    ReviewComment(
                        category="integrity",
                        severity="warning",
                        message="直接引语的证据片段缺少页码。",
                        recommendation="回看原文并补充准确页码或段落位置。",
                        location=claim.section,
                        claim_id=claim.id,
                    )
                )
        if claim.claim_type == "result" and re.search(r"\d", claim.text) and not claim_links:
            comments.append(
                ReviewComment(
                    category="method",
                    severity="error",
                    message="包含数值的研究结果缺少已核验来源。",
                    recommendation="关联数据表、方法记录或已导入文献中的证据片段。",
                    location=claim.section,
                    claim_id=claim.id,
                )
            )
    if manuscript is not None:
        comments.extend(_review_manuscript_claims(manuscript, claims))
        if journal is not None:
            comments.extend(review_journal_conformance(manuscript, journal))
    deduplicated = _deduplicate_comments(comments)
    return IntegrityReview(
        citation_audit=audit,
        comments=deduplicated,
        passed=not any(comment.severity == "error" for comment in deduplicated),
    )


def manuscript_word_count(manuscript: str) -> int:
    """Count CJK characters and Latin/number word groups deterministically.

    This mixed-language metric avoids treating an entire Chinese paragraph as one
    whitespace-delimited word while keeping common English compounds together.
    """

    return len(_CJK_OR_WORD.findall(manuscript))


def review_journal_conformance(
    manuscript: str,
    journal: JournalProfile,
) -> list[ReviewComment]:
    """Check machine-verifiable manuscript limits from one journal profile.

    The checker covers the profile's required sections and length limits.  Every
    free-form custom rule remains an individual, unresolved human-review item.
    """

    comments: list[ReviewComment] = []
    lines = [line.strip() for line in manuscript.replace("\r\n", "\n").split("\n")]
    nonempty_lines = [line for line in lines if line]
    title = _extract_title(nonempty_lines)

    if journal.title_max_characters is not None:
        if not title:
            comments.append(
                ReviewComment(
                    category="style",
                    severity="error",
                    message=f"未识别到题名，尚未核对《{journal.name}》的题名长度上限。",
                    recommendation="将稿件题名置于首个非空行后重新审校。",
                    location="题名",
                )
            )
        else:
            title_characters = _visible_character_count(title)
            if title_characters > journal.title_max_characters:
                comments.append(
                    ReviewComment(
                        category="style",
                        severity="error",
                        message=(
                            f"题名共 {title_characters} 个字符，超过《{journal.name}》"
                            f"上限 {journal.title_max_characters} 个字符。"
                        ),
                        recommendation="压缩题名并保留研究对象、核心问题和必要限定语。",
                        location="题名",
                    )
                )

    headings = {_canonical_heading(line) for line in nonempty_lines}
    headings.discard("")
    for required_section in journal.required_sections:
        normalized_required = _canonical_heading(required_section)
        if normalized_required and not _has_required_section(
            normalized_required,
            nonempty_lines,
            headings,
        ):
            comments.append(
                ReviewComment(
                    category="style",
                    severity="error",
                    message=f"稿件缺少《{journal.name}》要求的“{required_section}”部分。",
                    recommendation=f"按投稿指南补充“{required_section}”并核对层级与顺序。",
                    location=required_section,
                )
            )

    if journal.abstract_max_characters is not None:
        abstract = _extract_abstract(lines, journal.required_sections)
        if abstract is None:
            comments.append(
                ReviewComment(
                    category="style",
                    severity="warning",
                    message=f"未识别到摘要正文，尚未核对《{journal.name}》的摘要长度上限。",
                    recommendation="使用独立的“摘要”标题或“摘要：正文”格式后重新审校。",
                    location="摘要",
                )
            )
        else:
            abstract_characters = _visible_character_count(abstract)
            if abstract_characters > journal.abstract_max_characters:
                comments.append(
                    ReviewComment(
                        category="style",
                        severity="error",
                        message=(
                            f"摘要共 {abstract_characters} 个字符，超过《{journal.name}》"
                            f"上限 {journal.abstract_max_characters} 个字符。"
                        ),
                        recommendation="压缩背景性表述，优先保留目的、方法、结果与结论。",
                        location="摘要",
                    )
                )

    if journal.manuscript_max_words is not None:
        words = manuscript_word_count(manuscript)
        if words > journal.manuscript_max_words:
            comments.append(
                ReviewComment(
                    category="style",
                    severity="error",
                    message=(
                        f"稿件按中日韩统一表意字符及拉丁词组计为 {words} 词，超过"
                        f"《{journal.name}》上限 {journal.manuscript_max_words} 词。"
                    ),
                    recommendation="按期刊篇幅要求压缩正文，并再次核对图表、脚注与参考文献是否计入。",
                    location="全文",
                )
            )

    for rule in journal.custom_rules:
        comments.append(
            ReviewComment(
                category="integrity",
                severity="info",
                message=f"期刊自定义要求需人工逐项核对：{rule}",
                recommendation="对照最新投稿指南和稿件原文记录核对结果；系统不推定该项已经满足。",
                location="投稿要求",
            )
        )
    return comments


def _review_manuscript_claims(
    manuscript: str,
    claims: Sequence[ResearchClaim],
) -> list[ReviewComment]:
    normalized_manuscript = _normalize_prose(manuscript)
    comments: list[ReviewComment] = []
    for claim in claims:
        normalized_claim = _normalize_prose(claim.text)
        if normalized_claim and normalized_claim not in normalized_manuscript:
            comments.append(
                ReviewComment(
                    category="consistency",
                    severity="warning",
                    message="用于引用核验的论断未在本次稿件中找到完全匹配的正文。",
                    recommendation="定位稿件中的实际表述，并同步更新论断文本或引用关联。",
                    location=claim.section,
                    claim_id=claim.id,
                )
            )
    return comments


def _extract_title(nonempty_lines: Sequence[str]) -> str:
    if not nonempty_lines:
        return ""
    title = re.sub(r"^#{1,6}\s*", "", nonempty_lines[0]).strip()
    title = re.sub(r"^(?:题名|标题)\s*[:：]\s*", "", title).strip()
    if _ABSTRACT_LINE.fullmatch(nonempty_lines[0]) or _KEYWORDS_LINE.match(nonempty_lines[0]):
        return ""
    return title


def _extract_abstract(
    lines: Sequence[str],
    section_names: Sequence[str] = (),
) -> str | None:
    for index, line in enumerate(lines):
        matched = _ABSTRACT_LINE.fullmatch(line)
        if matched is None:
            continue
        parts = [(matched.group(1) or "").strip()]
        for following in lines[index + 1 :]:
            if not following:
                continue
            if _KEYWORDS_LINE.match(following) or _is_probable_heading(
                following,
                section_names,
            ):
                break
            parts.append(following)
        return "\n".join(part for part in parts if part)
    return None


def _has_required_section(
    required: str,
    lines: Sequence[str],
    headings: set[str],
) -> bool:
    if required in headings:
        return True
    for line in lines:
        match = _ABSTRACT_LINE.fullmatch(line)
        if required == "摘要" and match is not None:
            return True
        heading = _canonical_heading(line)
        if heading.startswith(required + "：") or heading.startswith(required + ":"):
            return True
    return False


def _canonical_heading(value: str) -> str:
    normalized = value.strip().lstrip("\ufeff")
    while True:
        without_prefix = _HEADING_PREFIX.sub("", normalized, count=1).strip()
        if without_prefix == normalized:
            break
        normalized = without_prefix
    normalized = re.sub(r"[：:；;。．.]+$", "", normalized).strip()
    return re.sub(r"\s+", "", normalized).casefold()


def _is_probable_heading(value: str, section_names: Sequence[str] = ()) -> bool:
    stripped = value.strip()
    if re.match(r"^#{1,6}\s+\S", stripped):
        return True
    if _HEADING_PREFIX.match(stripped):
        return True
    canonical = _canonical_heading(stripped)
    configured = {_canonical_heading(name) for name in section_names}
    return bool(
        _KEYWORDS_LINE.match(stripped)
        or canonical in _COMMON_SECTION_HEADINGS
        or canonical in configured
    )


def _visible_character_count(value: str) -> int:
    return len(re.sub(r"\s+", "", value))


def _normalize_prose(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def _contains_direct_quote(value: str) -> bool:
    return bool(re.search(r"“[^”]+”|\"[^\"]+\"", value))


class _Identified(Protocol):
    id: str


def _unique[IdentifiedT: _Identified](
    items: Sequence[IdentifiedT], label: str
) -> dict[str, IdentifiedT]:
    result: dict[str, IdentifiedT] = {}
    for item in items:
        identifier = item.id
        if not identifier:
            raise ValueError(f"{label}对象缺少 ID")
        if identifier in result:
            raise ValueError(f"{label} ID 重复：{identifier}")
        result[identifier] = item
    return result


def _deduplicate_comments(comments: Sequence[ReviewComment]) -> list[ReviewComment]:
    result: list[ReviewComment] = []
    seen: set[tuple[str, str, str | None]] = set()
    for comment in comments:
        key = (comment.category, comment.message, comment.claim_id)
        if key not in seen:
            seen.add(key)
            result.append(comment)
    return result


__all__ = [
    "manuscript_word_count",
    "review_journal_conformance",
    "review_research_integrity",
    "verify_claim_citations",
]
