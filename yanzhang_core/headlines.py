"""Deterministic generation and scoring for high-value entry sentences."""

# Chinese candidate text intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from yanzhang_core.models import CoreModel, WritingBrief
from yanzhang_core.packs import HeadlineKind

_NUMBER = re.compile(r"\d[\d,.]*(?:%|％)?")
_UNKNOWN_SLOT = re.compile(r"\{[^{}]+\}")
_REPEATED_PUNCTUATION = re.compile(r"[，。！？：；、—]{3,}")
_WHITESPACE = re.compile(r"\s+")

type RhetoricalTechnique = Literal[
    "direct",
    "parallel",
    "antithesis",
    "progression",
    "main_subtitle",
    "triad",
    "quartet",
    "question",
    "normative",
    "evidence",
]


class CandidateRequest(CoreModel):
    """Inputs for title, opening, section-heading, or topic-sentence work."""

    brief: WritingBrief
    kind: HeadlineKind = "title"
    section_topic: str = Field(default="", max_length=300)
    count: int = Field(default=5, ge=1, le=12)
    required_terms: tuple[str, ...] = Field(default=(), max_length=16)
    formula_ids: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("required_terms", "formula_ids")
    @classmethod
    def validate_unique_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(term.strip() for term in values)
        if any(not term for term in cleaned):
            raise ValueError("列表字段不得包含空值")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("列表字段不得重复")
        return cleaned

    @model_validator(mode="after")
    def validate_formula_ids(self) -> Self:
        known = {formula.id for formula in _FORMULAS[self.kind]}
        unknown = tuple(formula_id for formula_id in self.formula_ids if formula_id not in known)
        if unknown:
            raise ValueError(f"formula_ids 含有不适用于 {self.kind} 的公式：{', '.join(unknown)}")
        return self


class HeadlineFormula(CoreModel):
    """Discoverable and explainable deterministic expression formula."""

    id: str = Field(min_length=1, max_length=100)
    kind: HeadlineKind
    name: str = Field(min_length=1, max_length=100)
    template: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=500)
    techniques: tuple[RhetoricalTechnique, ...] = Field(min_length=1, max_length=6)
    segment_count: int = Field(default=1, ge=1, le=4)

    @field_validator("techniques")
    @classmethod
    def validate_techniques(
        cls,
        values: tuple[RhetoricalTechnique, ...],
    ) -> tuple[RhetoricalTechnique, ...]:
        if len(values) != len(set(values)):
            raise ValueError("techniques 不得重复")
        return values


class CandidateScores(CoreModel):
    """Explainable channel-independent candidate score dimensions."""

    relevance: int = Field(ge=0, le=100)
    clarity: int = Field(ge=0, le=100)
    concision: int = Field(ge=0, le=100)
    rhythm: int = Field(ge=0, le=100)
    audience_fit: int = Field(ge=0, le=100)
    channel_fit: int = Field(ge=0, le=100)
    factual_restraint: int = Field(ge=0, le=100)


class TextCandidate(CoreModel):
    """One ranked piece of entry text with its formula and score evidence."""

    text: str = Field(min_length=1, max_length=1_000)
    kind: HeadlineKind
    formula_id: str = Field(min_length=1, max_length=100)
    formula_name: str = Field(min_length=1, max_length=100)
    techniques: tuple[RhetoricalTechnique, ...] = Field(min_length=1, max_length=6)
    rationale: str = Field(min_length=1, max_length=500)
    score: int = Field(ge=0, le=100)
    scores: CandidateScores
    rank: int = Field(ge=1, le=12)
    selected: bool = False


class CandidateBatch(CoreModel):
    """A deterministic ranked result for one entry-sentence request."""

    kind: HeadlineKind
    recommended: str = Field(min_length=1, max_length=1_000)
    candidates: tuple[TextCandidate, ...] = Field(min_length=1, max_length=12)
    scoring_weights: dict[str, int]


_SCORING_WEIGHTS: dict[str, int] = {
    "relevance": 25,
    "clarity": 15,
    "concision": 15,
    "rhythm": 10,
    "audience_fit": 10,
    "channel_fit": 15,
    "factual_restraint": 10,
}


def _formula(
    formula_id: str,
    kind: HeadlineKind,
    name: str,
    template: str,
    rationale: str,
    *techniques: RhetoricalTechnique,
    segment_count: int = 1,
) -> HeadlineFormula:
    return HeadlineFormula(
        id=formula_id,
        kind=kind,
        name=name,
        template=template,
        rationale=rationale,
        techniques=techniques,
        segment_count=segment_count,
    )


_FORMULAS: dict[HeadlineKind, tuple[HeadlineFormula, ...]] = {
    "title": (
        _formula(
            "direct", "title", "直陈主题", "{topic}", "直接呈现主题，便于识别与检索。", "direct"
        ),
        _formula(
            "purpose",
            "title",
            "主题加目标",
            "{topic}：{goal}",
            "用主题和目标建立清晰的信息层级。",
            "direct",
        ),
        _formula(
            "main-subtitle",
            "title",
            "主副题",
            "把{focus}讲清楚——关于{topic}的{content_type}",
            "主标题强调表达焦点，副标题交代主题和文种。",
            "main_subtitle",
            segment_count=2,
        ),
        _formula(
            "parallel-triad",
            "title",
            "三段式排比",
            "把准{focus}、抓住关键、推动{topic}",
            "用三段同构动作形成排比节奏，同时保留主题信息。",
            "parallel",
            "triad",
            segment_count=3,
        ),
        _formula(
            "parallel-quartet",
            "title",
            "四段式排比",
            "明方向、抓重点、强协同、促落实——{topic}",
            "用四个克制的行动短语形成完整工作链条。",
            "parallel",
            "quartet",
            "main_subtitle",
            segment_count=4,
        ),
        _formula(
            "antithesis",
            "title",
            "对偶式",
            "既看{focus}，更看落实——{topic}",
            "以对偶结构并置关注重点和结果要求。",
            "antithesis",
            "main_subtitle",
            segment_count=2,
        ),
        _formula(
            "progression",
            "title",
            "递进式",
            "从看清{focus}到推动{topic}落地",
            "按认识、行动的递进关系表达路径。",
            "progression",
            segment_count=2,
        ),
        _formula(
            "numbered-quartet",
            "title",
            "一二三四式",
            "一看方向、二看重点、三看行动、四看实效——{topic}",
            "以四个并列观察维度增强记忆点，不引入未经材料支持的数据。",
            "parallel",
            "quartet",
            "main_subtitle",
            segment_count=4,
        ),
        _formula(
            "action",
            "title",
            "行动式",
            "聚焦{focus}，推进{topic}",
            "用行动动词强化任务导向。",
            "direct",
            segment_count=2,
        ),
        _formula(
            "question",
            "title",
            "设问式",
            "怎样把{topic}落到实处",
            "用问题式标题突出解决导向。",
            "question",
        ),
        _formula(
            "audience",
            "title",
            "受众式",
            "面向{audience}的{topic}",
            "把目标读者纳入标题语境。",
            "direct",
        ),
        _formula(
            "document",
            "title",
            "规范文种式",
            "关于{topic}的{content_type}",
            "以主题和成果类型构成规范标题。",
            "normative",
        ),
        _formula(
            "compact",
            "title",
            "短语式",
            "{focus}行动指南",
            "用简短结构强调可执行性。",
            "direct",
        ),
    ),
    "opening": (
        _formula(
            "direct",
            "opening",
            "开门见山",
            "围绕{topic}，本文重点说明{goal}。",
            "首句直接交代主题与目的。",
            "direct",
        ),
        _formula(
            "parallel-triad",
            "opening",
            "三句排比",
            "看清{focus}，才能把准方向；抓住重点，才能形成行动；围绕{topic}，才能实现{goal}。",
            "用三层条件句形成节奏，并由认识递进至目标。",
            "parallel",
            "triad",
            "progression",
            segment_count=3,
        ),
        _formula(
            "parallel-quartet",
            "opening",
            "四句排比",
            "方向要明，重点要准，行动要实，结果要可检验；这正是{topic}需要回答的问题。",
            "用四个同构判断句概括全文逻辑，不预设具体成效。",
            "parallel",
            "quartet",
            segment_count=4,
        ),
        _formula(
            "antithesis",
            "opening",
            "对偶判断",
            "推进{topic}，既要把{focus}谋清楚，也要把{goal}落到行动中。",
            "以既要、也要构成对偶，兼顾认识和实践。",
            "antithesis",
            segment_count=2,
        ),
        _formula(
            "progression",
            "opening",
            "递进导入",
            "先看清{focus}，再明确行动路径，最终要用{goal}检验{topic}。",
            "按认识、行动、检验三层递进导入正文。",
            "progression",
            "triad",
            segment_count=3,
        ),
        _formula(
            "audience",
            "opening",
            "读者切入",
            "对{audience}而言，{topic}首先要回答的是：{goal}。",
            "从读者关切切入。",
            "direct",
        ),
        _formula(
            "question",
            "opening",
            "设问导入",
            "如何围绕{topic}实现{goal}？答案要从{focus}中寻找。",
            "以问答结构形成牵引。",
            "question",
        ),
        _formula(
            "contrast",
            "opening",
            "对比导入",
            "比写得更多更重要的，是围绕{topic}把{focus}写准确。",
            "用对比突出重点。",
            "antithesis",
        ),
        _formula(
            "evidence",
            "opening",
            "证据边界",
            "讨论{topic}，应从已知材料出发，把{focus}说清楚，把{goal}落具体。",
            "开篇即说明材料边界和写作任务。",
            "evidence",
            "parallel",
            segment_count=2,
        ),
        _formula(
            "compact",
            "opening",
            "短句点题",
            "{topic}，重在{focus}，成在行动。",
            "以短句形成节奏和观点。",
            "parallel",
            "triad",
            segment_count=3,
        ),
    ),
    "section_heading": (
        _formula("direct", "section_heading", "直陈式", "{focus}", "直接标记本节主题。", "direct"),
        _formula(
            "parallel-triad",
            "section_heading",
            "三段式排比",
            "找准{focus}、抓住重点、形成闭环",
            "以三个同构动作构成小标题。",
            "parallel",
            "triad",
            segment_count=3,
        ),
        _formula(
            "parallel-quartet",
            "section_heading",
            "四段式排比",
            "明晰{focus}、细化任务、压实责任、检验结果",
            "以四个动作呈现从认识到检验的完整链条。",
            "parallel",
            "quartet",
            "progression",
            segment_count=4,
        ),
        _formula(
            "antithesis",
            "section_heading",
            "对偶式",
            "既把准{focus}，又抓实具体行动",
            "用对偶关系连接方向和行动。",
            "antithesis",
            segment_count=2,
        ),
        _formula(
            "progression",
            "section_heading",
            "递进式",
            "从明确{focus}到形成工作闭环",
            "用从、到呈现章节的递进方向。",
            "progression",
            segment_count=2,
        ),
        _formula(
            "topic-colon",
            "section_heading",
            "主副式小标题",
            "{focus}：把认识转化为行动",
            "冒号前点题，冒号后说明本节推进方向。",
            "main_subtitle",
            segment_count=2,
        ),
        _formula(
            "action",
            "section_heading",
            "行动式",
            "聚焦{focus}，明确行动重点",
            "用行动式短语建立章节方向。",
            "direct",
            segment_count=2,
        ),
        _formula(
            "problem",
            "section_heading",
            "问题式",
            "正视{focus}中的关键问题",
            "以问题导向组织分析。",
            "question",
        ),
        _formula(
            "solution",
            "section_heading",
            "对策式",
            "围绕{focus}完善解决路径",
            "从主题自然转入对策。",
            "direct",
        ),
        _formula(
            "mechanism",
            "section_heading",
            "机制式",
            "健全{focus}的长效机制",
            "适用于制度和持续改进内容。",
            "normative",
        ),
    ),
    "topic_sentence": (
        _formula(
            "direct",
            "topic_sentence",
            "直接统领",
            "本段围绕{focus}展开，重点说明{goal}。",
            "明确本段范围和目的。",
            "direct",
        ),
        _formula(
            "parallel-triad",
            "topic_sentence",
            "三层排比",
            "认识{focus}要把准方向，推进{focus}要抓住重点，检验{focus}要回到结果。",
            "用三个同构分句统领本段的认识、行动和检验。",
            "parallel",
            "triad",
            "progression",
            segment_count=3,
        ),
        _formula(
            "parallel-quartet",
            "topic_sentence",
            "四层排比",
            "围绕{focus}，方向要明、任务要细、责任要实、结果要可检验。",
            "用四个同构要求概括段落论证框架。",
            "parallel",
            "quartet",
            segment_count=4,
        ),
        _formula(
            "antithesis",
            "topic_sentence",
            "对偶判断",
            "做好{focus}，既要把握整体，也要拆解具体步骤。",
            "以整体和具体构成对偶，统领方法分析。",
            "antithesis",
            segment_count=2,
        ),
        _formula(
            "progression",
            "topic_sentence",
            "递进判断",
            "{focus}要从明确目标起步，经由具体行动，最终接受结果检验。",
            "按目标、行动、检验依次递进。",
            "progression",
            "triad",
            segment_count=3,
        ),
        _formula(
            "judgement",
            "topic_sentence",
            "观点判断",
            "{focus}是推进{topic}必须把握的关键环节。",
            "用判断句统领段落。",
            "direct",
        ),
        _formula(
            "evidence",
            "topic_sentence",
            "证据边界",
            "分析{focus}，应当回到已有材料和可核查事实。",
            "提示段落遵循证据边界。",
            "evidence",
        ),
        _formula(
            "audience",
            "topic_sentence",
            "受众关联",
            "对{audience}而言，{focus}直接关系到{goal}。",
            "把主题与目标读者连接起来。",
            "direct",
        ),
        _formula(
            "transition",
            "topic_sentence",
            "递进过渡",
            "在明确总体方向后，下一步要把重点转向{focus}。",
            "承担章节间过渡功能。",
            "progression",
        ),
        _formula(
            "contrast",
            "topic_sentence",
            "对比聚焦",
            "与其泛泛讨论{topic}，更需要把{focus}分析透彻。",
            "通过对比压实本段焦点。",
            "antithesis",
        ),
    ),
}


def generate_candidates(request: CandidateRequest) -> CandidateBatch:
    """Generate, score, and rank a repeatable candidate batch offline."""

    context = _template_context(request)
    generated: list[tuple[int, int, str, HeadlineFormula, CandidateScores]] = []
    seen: set[str] = set()
    selected_ids = set(request.formula_ids)
    formulas = (
        formula
        for formula in _FORMULAS[request.kind]
        if not selected_ids or formula.id in selected_ids
    )
    for order, formula in enumerate(formulas):
        text = _normalize_text(formula.template.format_map(context))
        if not text or text in seen:
            continue
        seen.add(text)
        scores = score_candidate(text, request)
        generated.append((_weighted_score(scores), -order, text, formula, scores))
    generated.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = generated[: request.count]

    candidates = tuple(
        TextCandidate(
            text=text,
            kind=request.kind,
            formula_id=formula.id,
            formula_name=formula.name,
            techniques=formula.techniques,
            rationale=formula.rationale,
            score=score,
            scores=scores,
            rank=rank,
            selected=rank == 1,
        )
        for rank, (score, _, text, formula, scores) in enumerate(selected, 1)
    )
    if not candidates:
        raise ValueError("没有生成可用候选")
    return CandidateBatch(
        kind=request.kind,
        recommended=candidates[0].text,
        candidates=candidates,
        scoring_weights=dict(_SCORING_WEIGHTS),
    )


def list_headline_formulas(kind: HeadlineKind | None = None) -> tuple[HeadlineFormula, ...]:
    """List the stable formula catalog, optionally scoped to one expression kind."""

    if kind is not None:
        return _FORMULAS[kind]
    return tuple(formula for formulas in _FORMULAS.values() for formula in formulas)


def score_candidate(text: str, request: CandidateRequest) -> CandidateScores:
    """Score user- or engine-supplied entry text using the same local contract."""

    value = _normalize_text(text)
    topic = request.brief.title
    terms = (topic, *request.brief.keywords, *request.required_terms)
    relevant_terms = tuple(term for term in terms if term)
    matches = sum(term in value for term in relevant_terms)
    relevance = (
        65 if not relevant_terms else min(100, 55 + round(45 * matches / len(relevant_terms)))
    )
    if topic in value:
        relevance = max(relevance, 92)

    clarity = 100
    if _UNKNOWN_SLOT.search(value):
        clarity -= 50
    if _REPEATED_PUNCTUATION.search(value):
        clarity -= 20
    if "  " in text or "\n" in text.strip():
        clarity -= 10
    if not value.endswith(("。", "？", "！")) and request.kind in {"opening", "topic_sentence"}:
        clarity -= 5

    ideal_min, ideal_max = _ideal_length(request.kind, request.brief.channel)
    length = len(value)
    if ideal_min <= length <= ideal_max:
        concision = 100
    elif length < ideal_min:
        concision = max(55, 100 - (ideal_min - length) * 5)
    else:
        concision = max(20, 100 - (length - ideal_max) * 3)

    segments = tuple(part for part in re.split(r"[，、：；—]", value) if part)
    rhythm = 65
    if 2 <= len(segments) <= 4:
        rhythm += 20
    if len(segments) >= 2 and max(map(len, segments)) - min(map(len, segments)) <= 8:
        rhythm += 10
    if any(marker in value for marker in ("既要", "也要", "从", "到", "关键", "重在", "成在")):
        rhythm += 5

    audience_fit = 100 if request.brief.audience in value else 82
    if request.brief.tone and any(term in value for term in request.brief.tone.split("、")):
        audience_fit = min(100, audience_fit + 5)

    channel_fit = _channel_fit(value, request.kind, request.brief.channel)
    factual_restraint = 100
    source_text = " ".join(
        (
            request.brief.title,
            request.brief.goal,
            *request.brief.constraints,
            *request.brief.keywords,
        )
    )
    unsupported_numbers = tuple(
        number for number in _NUMBER.findall(value) if number not in source_text
    )
    if unsupported_numbers:
        factual_restraint = max(20, 100 - len(unsupported_numbers) * 35)

    return CandidateScores(
        relevance=_bound(relevance),
        clarity=_bound(clarity),
        concision=_bound(concision),
        rhythm=_bound(rhythm),
        audience_fit=_bound(audience_fit),
        channel_fit=_bound(channel_fit),
        factual_restraint=_bound(factual_restraint),
    )


def generate_headlines(brief: WritingBrief, *, count: int = 5) -> CandidateBatch:
    """Convenience entry point for complete-document titles."""

    return generate_candidates(CandidateRequest(brief=brief, kind="title", count=count))


def generate_openings(brief: WritingBrief, *, count: int = 5) -> CandidateBatch:
    """Convenience entry point for document opening sentences."""

    return generate_candidates(CandidateRequest(brief=brief, kind="opening", count=count))


def generate_section_headings(
    brief: WritingBrief, section_topic: str, *, count: int = 5
) -> CandidateBatch:
    """Convenience entry point for section-heading candidates."""

    return generate_candidates(
        CandidateRequest(
            brief=brief,
            kind="section_heading",
            section_topic=section_topic,
            count=count,
        )
    )


def generate_topic_sentences(
    brief: WritingBrief, section_topic: str, *, count: int = 5
) -> CandidateBatch:
    """Convenience entry point for paragraph topic-sentence candidates."""

    return generate_candidates(
        CandidateRequest(
            brief=brief,
            kind="topic_sentence",
            section_topic=section_topic,
            count=count,
        )
    )


def _template_context(request: CandidateRequest) -> dict[str, str]:
    brief = request.brief
    focus = request.section_topic or (brief.keywords[0] if brief.keywords else brief.title)
    return {
        "topic": brief.title,
        "goal": brief.goal.rstrip("。！？"),
        "audience": brief.audience,
        "content_type": brief.content_type,
        "focus": focus,
    }


def _normalize_text(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip(" ，")


def _ideal_length(kind: HeadlineKind, channel: str) -> tuple[int, int]:
    if kind == "title":
        return (8, 28 if channel in {"email", "social"} else 36)
    if kind == "section_heading":
        return (6, 28)
    if kind == "opening":
        return (18, 72 if channel == "social" else 100)
    return (15, 90)


def _channel_fit(text: str, kind: HeadlineKind, channel: str) -> int:
    length = len(text)
    if channel == "email" and kind == "title":
        return 100 if 6 <= length <= 28 else 65
    if channel == "social":
        return 100 if length <= 72 else max(30, 100 - (length - 72) * 3)
    if channel == "presentation":
        return 100 if length <= 32 else max(40, 100 - (length - 32) * 2)
    if channel == "academic":
        return 96 if not any(mark in text for mark in ("！", "？")) else 70
    return 94 if length <= 100 else 75


def _weighted_score(scores: CandidateScores) -> int:
    values: dict[str, int] = {
        "relevance": scores.relevance,
        "clarity": scores.clarity,
        "concision": scores.concision,
        "rhythm": scores.rhythm,
        "audience_fit": scores.audience_fit,
        "channel_fit": scores.channel_fit,
        "factual_restraint": scores.factual_restraint,
    }
    return round(sum(values[key] * weight for key, weight in _SCORING_WEIGHTS.items()) / 100)


def _bound(value: int) -> int:
    return max(0, min(100, value))


__all__ = [
    "CandidateBatch",
    "CandidateRequest",
    "CandidateScores",
    "HeadlineFormula",
    "RhetoricalTechnique",
    "TextCandidate",
    "generate_candidates",
    "generate_headlines",
    "generate_openings",
    "generate_section_headings",
    "generate_topic_sentences",
    "list_headline_formulas",
    "score_candidate",
]
