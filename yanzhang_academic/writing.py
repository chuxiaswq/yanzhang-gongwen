"""Deterministic, evidence-bounded academic writing assistance."""

# ruff: noqa: RUF001 -- Chinese writing output uses full-width punctuation.

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from yanzhang_academic.citations import format_in_text_citation
from yanzhang_academic.models import (
    AbstractDraft,
    AcademicOutline,
    BibliographicRecord,
    ClaimCitationLink,
    EvidenceSnippet,
    JournalProfile,
    OutlineSection,
    RebuttalItem,
    ResearchBrief,
    ResearchClaim,
    ReviewComment,
    TitleSuggestion,
)


def suggest_titles(
    brief: ResearchBrief,
    records: Sequence[BibliographicRecord] = (),
    *,
    count: int = 5,
) -> list[TitleSuggestion]:
    """Suggest bounded titles without introducing facts outside the research brief."""

    if count < 1 or count > 10:
        raise ValueError("count 必须在 1 到 10 之间")
    topic = _compact_topic(brief.title)
    question = _compact_topic(brief.research_question)
    keyword = brief.keywords[0] if brief.keywords else topic
    discipline = brief.discipline or "相关领域"
    templates = [
        (topic, "直接呈现用户确认的研究主题"),
        (f"{topic}：问题、机制与路径", "以并列结构呈现问题意识和分析层次"),
        (f"从{keyword}看{topic}", "突出用户给定的核心关键词"),
        (f"{topic}的理论逻辑与实践进路", "适合理论联系实践的研究结构"),
        (f"{question}——基于{discipline}视角的考察", "直接回应研究问题并标明学科视角"),
        (f"何以理解{topic}：证据、解释与边界", "突出证据和论证边界"),
        (f"{topic}研究：现状、争议与展望", "适合文献综述型成果"),
        (f"迈向{keyword}：{topic}的分析框架", "突出框架建构与研究方向"),
        (f"{topic}中的关键问题及其解释", "强调问题导向"),
        (f"重新审视{topic}：基于既有研究的综合分析", "适合证据综合型研究"),
    ]
    record_ids = [record.id for record in records]
    result: list[TitleSuggestion] = []
    seen: set[str] = set()
    for title, rationale in templates:
        normalized = _trim_title(title)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(
                TitleSuggestion(title=normalized, rationale=rationale, record_ids=record_ids)
            )
        if len(result) == count:
            break
    return result


def create_outline(
    brief: ResearchBrief,
    records: Sequence[BibliographicRecord] = (),
    evidence: Sequence[EvidenceSnippet] = (),
    *,
    journal: JournalProfile | None = None,
) -> AcademicOutline:
    """Create an outline whose source links are restricted to imported records."""

    record_map = {record.id: record for record in records}
    valid_evidence = [
        snippet
        for snippet in evidence
        if snippet.record_id in record_map
        and snippet.record_source_hash == record_map[snippet.record_id].source_hash
    ]
    record_ids = list(record_map)
    requested = journal.required_sections if journal and journal.required_sections else []
    headings = requested or ["引言", "文献综述", "研究设计", "研究发现", "讨论", "结论"]
    sections: list[OutlineSection] = []
    for heading in headings:
        purpose, kinds = _section_plan(heading, brief)
        selected = [snippet for snippet in valid_evidence if snippet.kind in kinds]
        selected_record_ids = list(dict.fromkeys(snippet.record_id for snippet in selected))
        if heading in {"文献综述", "研究现状"} and not selected_record_ids:
            selected_record_ids = record_ids
        sections.append(
            OutlineSection(
                heading=heading,
                purpose=purpose,
                questions=_section_questions(heading, brief),
                record_ids=selected_record_ids,
                evidence_ids=[snippet.id for snippet in selected],
            )
        )
    return AcademicOutline(
        title=suggest_titles(brief, records, count=1)[0].title,
        sections=sections,
        record_ids=record_ids,
    )


def draft_abstract(
    brief: ResearchBrief,
    claims: Sequence[ResearchClaim],
    links: Sequence[ClaimCitationLink],
    records: Sequence[BibliographicRecord],
    *,
    journal: JournalProfile | None = None,
) -> AbstractDraft:
    """Assemble an abstract only from the brief and previously verified links."""

    record_map = {record.id: record for record in records}
    claim_map = {claim.id: claim for claim in claims}
    valid_links = [
        link
        for link in links
        if link.status == "verified"
        and link.verified_at is not None
        and link.relation == "supports"
        and link.claim_id in claim_map
        and link.record_id in record_map
    ]
    links_by_claim: dict[str, list[ClaimCitationLink]] = {}
    for link in valid_links:
        links_by_claim.setdefault(link.claim_id, []).append(link)
    supported_claims = [claim for claim in claims if claim.id in links_by_claim]

    parts = [f"本研究围绕“{brief.research_question}”展开。"]
    if brief.purpose:
        parts.append(f"研究旨在{_sentence_fragment(brief.purpose)}。")
    placeholders: list[str] = []
    if brief.method_notes:
        parts.append(f"研究采用{_sentence_fragment(brief.method_notes)}。")
    else:
        placeholder = "【研究方法与资料范围待确认】"
        placeholders.append(placeholder)
        parts.append(placeholder)
    for claim in supported_claims[:3]:
        first_link = links_by_claim[claim.id][0]
        record = record_map[first_link.record_id]
        citation = format_in_text_citation(record, "apa")
        parts.append(f"现有证据表明，{_sentence_fragment(claim.text)}{citation}。")
    if not supported_claims:
        placeholder = "【经引用核验的主要发现待补充】"
        placeholders.append(placeholder)
        parts.append(placeholder)
    parts.append("研究结论的适用范围以已导入资料和人工确认的研究边界为准。")
    text = "".join(parts)
    limit = journal.abstract_max_characters if journal else None
    if limit is not None and len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip("，,；;。. ") + "。"
    source_ids = list(dict.fromkeys(link.record_id for link in valid_links))
    return AbstractDraft(
        text=text,
        record_ids=source_ids,
        claim_ids=[claim.id for claim in supported_claims[:3]],
        placeholders=placeholders,
    )


def prepare_rebuttal(
    comments: Sequence[ReviewComment],
    changes: Mapping[str, str] | None = None,
) -> list[RebuttalItem]:
    """Prepare traceable point-by-point response drafts."""

    change_map = changes or {}
    result: list[RebuttalItem] = []
    for comment in comments:
        change = " ".join(change_map.get(comment.id, "").split())
        if change:
            response = f"感谢审稿人的意见。我们已据此核对并完成修改：{change}。"
            status = "confirmed"
        else:
            response = (
                "感谢审稿人的意见。我们将结合原始资料逐项核对，并在正文及回复中说明"
                "具体修改位置和依据。"
            )
            status = "draft"
            change = "【请补充具体修改内容和页码】"
        result.append(
            RebuttalItem(
                comment_id=comment.id,
                reviewer_comment=comment.message,
                response=response,
                manuscript_change=change,
                location=comment.location,
                status=status,
            )
        )
    return result


def _section_plan(heading: str, brief: ResearchBrief) -> tuple[str, set[str]]:
    normalized = heading.casefold()
    if any(term in normalized for term in ("引言", "绪论", "背景", "introduction")):
        return (
            f"说明{brief.research_question}的背景、问题意识与研究价值。",
            {"background", "definition"},
        )
    if any(term in normalized for term in ("文献", "研究现状", "literature")):
        return (
            "比较既有研究的主要观点、证据、分歧与缺口。",
            {"background", "finding", "limitation", "definition"},
        )
    if any(term in normalized for term in ("方法", "设计", "method")):
        return "交代研究设计、资料来源、分析方法与适用边界。", {"method"}
    if any(term in normalized for term in ("发现", "结果", "result", "finding")):
        return "依据材料呈现研究发现，并区分观察结果与解释。", {"finding"}
    if any(term in normalized for term in ("讨论", "discussion")):
        return "解释发现、对照既有研究并分析局限。", {"finding", "limitation"}
    if any(term in normalized for term in ("结论", "conclusion")):
        return "回应研究问题，概括贡献、边界与后续方向。", {"finding", "limitation"}
    return f"围绕“{brief.research_question}”完成本节论证。", {"other", "background", "finding"}


def _section_questions(heading: str, brief: ResearchBrief) -> list[str]:
    return [
        f"本节如何回应研究问题：{brief.research_question}",
        "本节的关键论断分别由哪些已导入证据支持？",
        "本节结论的适用范围和限制是什么？",
    ]


def _compact_topic(value: str) -> str:
    normalized = " ".join(value.split()).strip("。！？!?；;：:，, ")
    return normalized[:80]


def _trim_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:120]


def _sentence_fragment(value: str) -> str:
    return " ".join(value.split()).strip("。！？!?；;，, ")


__all__ = ["create_outline", "draft_abstract", "prepare_rebuttal", "suggest_titles"]
