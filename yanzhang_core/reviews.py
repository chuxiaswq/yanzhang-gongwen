"""Offline six-dimension review for every Yanzhang text asset."""

# Chinese review messages intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import re
from collections import Counter
from typing import Literal

from pydantic import Field

from yanzhang_core.models import (
    ContentBlock,
    CoreModel,
    Evidence,
    ProjectTerm,
    TextAsset,
    WritingBrief,
)
from yanzhang_core.provenance import checkable_fact_anchors

type ReviewDimension = Literal[
    "evidence",
    "logic",
    "clarity",
    "audience_tone",
    "language",
    "format",
]
type ReviewSeverity = Literal["info", "warning", "error"]

_DIMENSIONS: tuple[ReviewDimension, ...] = (
    "evidence",
    "logic",
    "clarity",
    "audience_tone",
    "language",
    "format",
)
_DIMENSION_LABELS: dict[ReviewDimension, str] = {
    "evidence": "事实与证据",
    "logic": "逻辑与结构",
    "clarity": "清晰与简洁",
    "audience_tone": "受众与语气",
    "language": "语言与规范",
    "format": "格式与交付",
}
_NUMBER = re.compile(r"\d[\d,.]*(?:%|％)?")
_SENTENCE = re.compile(r"[^。！？!?；;]+[。！？!?；;]?")
_REPEATED_PUNCTUATION = re.compile(r"([，。！？：；、])\1+")
_EMOJI_OR_DECORATION = re.compile(r"[😀-🙏🚀-🛿✨★☆❤]|#{2,}")
_COLLOQUIAL = ("哈哈", "随便", "搞定", "绝绝子", "冲一波", "YYDS")


class ReviewRequest(CoreModel):
    """A complete input bundle for deterministic review."""

    asset: TextAsset
    brief: WritingBrief | None = None
    evidence: tuple[Evidence, ...] = Field(default=(), max_length=10_000)
    terms: tuple[ProjectTerm, ...] = Field(default=(), max_length=5_000)


class ReviewIssue(CoreModel):
    """One actionable issue located at a content block."""

    id: str = Field(min_length=1, max_length=64)
    dimension: ReviewDimension
    severity: ReviewSeverity
    block_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1_000)
    suggestion: str = Field(min_length=1, max_length=1_000)


class ReviewDimensionScore(CoreModel):
    """Score and compact explanation for one review dimension."""

    dimension: ReviewDimension
    label: str = Field(min_length=1, max_length=100)
    score: int = Field(ge=0, le=100)
    issue_count: int = Field(ge=0)
    summary: str = Field(min_length=1, max_length=500)


class ReviewMetrics(CoreModel):
    """Stable measurements used to explain a review report."""

    character_count: int = Field(ge=0)
    block_count: int = Field(ge=0)
    claim_like_count: int = Field(ge=0)
    cited_claim_like_count: int = Field(ge=0)
    evidence_coverage: int = Field(ge=0, le=100)


class ReviewReport(CoreModel):
    """Complete six-dimension local review output."""

    asset_id: str = Field(min_length=1, max_length=128)
    overall_score: int = Field(ge=0, le=100)
    passed: bool
    dimensions: tuple[ReviewDimensionScore, ...] = Field(min_length=6, max_length=6)
    issues: tuple[ReviewIssue, ...]
    metrics: ReviewMetrics


def review_asset(
    asset: TextAsset,
    *,
    brief: WritingBrief | None = None,
    evidence: tuple[Evidence, ...] = (),
    terms: tuple[ProjectTerm, ...] = (),
) -> ReviewReport:
    """Review one asset locally across evidence, logic, clarity, tone, language, and format."""

    return run_review(ReviewRequest(asset=asset, brief=brief, evidence=evidence, terms=terms))


def run_review(request: ReviewRequest) -> ReviewReport:
    """Execute the deterministic six-dimension review contract."""

    raw_issues: list[tuple[ReviewDimension, ReviewSeverity, str | None, str, str]] = []

    def add(
        dimension: ReviewDimension,
        severity: ReviewSeverity,
        block: ContentBlock | None,
        message: str,
        suggestion: str,
    ) -> None:
        raw_issues.append((dimension, severity, block.id if block else None, message, suggestion))

    asset = request.asset
    structural_topic = request.brief.title if request.brief is not None else None
    evidence_by_id = {item.id: item for item in request.evidence}
    evidence_anchors = {item.id: checkable_fact_anchors(item.excerpt) for item in request.evidence}
    evidence_ids = set(evidence_by_id)
    claim_like_count = 0
    cited_claim_like_count = 0

    for block in asset.blocks:
        numbers = _NUMBER.findall(block.text)
        if numbers:
            claim_like_count += 1
            linked_evidence = tuple(
                evidence_by_id[evidence_id]
                for evidence_id in block.evidence_ids
                if evidence_id in evidence_by_id
            )
            required_anchors = checkable_fact_anchors(
                block.text,
                structural_topic=structural_topic,
            )
            available_anchors = frozenset().union(
                *(evidence_anchors[item.id] for item in linked_evidence)
            )
            if (
                block.evidence_ids
                and len(linked_evidence) == len(block.evidence_ids)
                and required_anchors.issubset(available_anchors)
            ):
                cited_claim_like_count += 1
            else:
                message = (
                    f"包含 {len(numbers)} 项数字表达，但本段尚未关联证据。"
                    if not block.evidence_ids
                    else f"包含 {len(numbers)} 项数字表达，但已关联证据未覆盖全部事实锚点。"
                )
                add(
                    "evidence",
                    "warning",
                    block,
                    message,
                    "为数字、比例、日期或数量补充来源定位，或改为明确的待核实标记。",
                )
        missing_ids = tuple(item for item in block.evidence_ids if item not in evidence_ids)
        if missing_ids:
            add(
                "evidence",
                "error",
                block,
                "内容块引用了当前审校输入中不存在的证据标识。",
                "补充对应证据摘录，或移除失效的证据关系。",
            )

    body_blocks = tuple(block for block in asset.blocks if block.kind == "paragraph" and block.text)
    normalized_bodies = tuple(_normalize(block.text) for block in body_blocks)
    duplicate_bodies = {text for text, count in Counter(normalized_bodies).items() if count > 1}
    for block in body_blocks:
        if _normalize(block.text) in duplicate_bodies:
            add(
                "logic",
                "warning",
                block,
                "正文存在重复段落，可能造成论证原地打转。",
                "保留信息更完整的一段，并让后续段落承担新的论证任务。",
            )
    headings = tuple(block for block in asset.blocks if block.kind == "heading")
    if len(asset.blocks) >= 4 and not headings:
        add(
            "logic",
            "info",
            None,
            "较长文稿尚未使用章节标题呈现逻辑层次。",
            "按论证任务拆分章节，并为每节设置能够概括结论的小标题。",
        )

    for block in body_blocks:
        long_sentences = tuple(
            sentence.strip()
            for sentence in _SENTENCE.findall(block.text)
            if len(sentence.strip()) > 90
        )
        if long_sentences:
            add(
                "clarity",
                "warning",
                block,
                f"本段有 {len(long_sentences)} 个句子超过90字。",
                "拆分并列成分，按“结论—依据—行动”改成更短句群。",
            )
        if len(block.text) > 600:
            add(
                "clarity",
                "warning",
                block,
                "单个段落超过600字，阅读负担较高。",
                "围绕一个中心句拆成两至三个段落。",
            )

    formal_channel = asset.channel in {"document", "email", "meeting", "academic"}
    for block in asset.blocks:
        colloquial = tuple(term for term in _COLLOQUIAL if term in block.text)
        if formal_channel and (colloquial or _EMOJI_OR_DECORATION.search(block.text)):
            add(
                "audience_tone",
                "warning",
                block,
                "当前表达与正式交付渠道的语气不一致。",
                "替换口语化、装饰性或情绪化表达，并保持语气稳定。",
            )
    if request.brief is not None and request.brief.audience not in asset.plain_text():
        add(
            "audience_tone",
            "info",
            None,
            "文稿未显式体现任务简报中的目标受众。",
            "检查信息顺序、解释深度和行动提示是否符合目标受众。",
        )

    for block in asset.blocks:
        if _REPEATED_PUNCTUATION.search(block.text) or "  " in block.text:
            add(
                "language",
                "warning",
                block,
                "存在重复标点或连续空格。",
                "统一标点与空格，清理输入或模型输出中的排版噪声。",
            )
        if not _brackets_balanced(block.text):
            add(
                "language",
                "error",
                block,
                "括号或引号未成对闭合。",
                "逐项检查括号、中文引号和书名号的开闭关系。",
            )
        for term in request.terms:
            matched = next(
                (variant for variant in term.discouraged_variants if variant in block.text),
                None,
            )
            if matched is not None:
                add(
                    "language",
                    "warning",
                    block,
                    f"使用了项目词表中的非首选表达“{matched}”。",
                    f"按项目约定使用“{term.preferred_form}”。",
                )

    heading_texts = tuple(_normalize(block.text) for block in headings if block.text)
    duplicate_headings = {text for text, count in Counter(heading_texts).items() if count > 1}
    for block in headings:
        if not block.text:
            add("format", "error", block, "存在空标题。", "填写标题或移除空标题块。")
        elif _normalize(block.text) in duplicate_headings:
            add(
                "format",
                "warning",
                block,
                "存在重复章节标题。",
                "区分章节任务，让标题准确反映各节内容。",
            )
    previous_level: int | None = None
    for block in headings:
        level = block.heading_level
        if previous_level is not None and level is not None and level > previous_level + 1:
            add(
                "format",
                "warning",
                block,
                "标题层级发生跨级跳转。",
                "按连续层级组织标题，避免从上级标题直接跳到更深层级。",
            )
        previous_level = level
    if not asset.title.strip():
        add("format", "error", None, "文字资产缺少标题。", "补充可识别的交付标题。")

    issues = tuple(
        ReviewIssue(
            id=f"issue-{index:03d}",
            dimension=dimension,
            severity=severity,
            block_id=block_id,
            message=message,
            suggestion=suggestion,
        )
        for index, (dimension, severity, block_id, message, suggestion) in enumerate(raw_issues, 1)
    )
    dimension_scores = tuple(_score_dimension(dimension, issues) for dimension in _DIMENSIONS)
    overall_score = round(sum(item.score for item in dimension_scores) / len(dimension_scores))
    evidence_coverage = (
        100 if claim_like_count == 0 else round(cited_claim_like_count * 100 / claim_like_count)
    )
    metrics = ReviewMetrics(
        character_count=len(asset.plain_text()),
        block_count=len(asset.blocks),
        claim_like_count=claim_like_count,
        cited_claim_like_count=cited_claim_like_count,
        evidence_coverage=evidence_coverage,
    )
    return ReviewReport(
        asset_id=asset.id,
        overall_score=overall_score,
        passed=overall_score >= 80 and all(issue.severity != "error" for issue in issues),
        dimensions=dimension_scores,
        issues=issues,
        metrics=metrics,
    )


def _score_dimension(
    dimension: ReviewDimension, issues: tuple[ReviewIssue, ...]
) -> ReviewDimensionScore:
    matching = tuple(issue for issue in issues if issue.dimension == dimension)
    penalties = {"info": 3, "warning": 10, "error": 25}
    score = max(0, 100 - sum(penalties[issue.severity] for issue in matching))
    summary = (
        "检查通过，未发现规则级问题。" if not matching else f"发现 {len(matching)} 项可处理问题。"
    )
    return ReviewDimensionScore(
        dimension=dimension,
        label=_DIMENSION_LABELS[dimension],
        score=score,
        issue_count=len(matching),
        summary=summary,
    )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _brackets_balanced(value: str) -> bool:
    pairs = (("（", "）"), ("(", ")"), ("“", "”"), ("《", "》"))
    return all(value.count(opening) == value.count(closing) for opening, closing in pairs)


__all__ = [
    "ReviewDimension",
    "ReviewDimensionScore",
    "ReviewIssue",
    "ReviewMetrics",
    "ReviewReport",
    "ReviewRequest",
    "ReviewSeverity",
    "review_asset",
    "run_review",
]
