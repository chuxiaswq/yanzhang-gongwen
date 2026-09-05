"""Deterministic title generation, scoring, and ranking."""

# Chinese punctuation is intentional in generated title copy.
# ruff: noqa: RUF001

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from gongwen_web.methodologies import (
    CustomTitleFormula,
    TitleFormulaDefinition,
    normalize_document_type,
    title_formulas_for,
)
from gongwen_web.models import (
    GenerateRequest,
    GenerationMeta,
    ProviderSettings,
    StyleReference,
    TitleCandidate,
)
from yanzhang_core.scenario_profiles import scenario_for_document_type

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_PLACEHOLDER = re.compile(r"\{(topic|document_type|purpose|audience)\}")
_UNKNOWN_PLACEHOLDER = re.compile(r"\{[^{}]+\}")
_ACTION_WORDS = ("推进", "落实", "加强", "提升", "深化", "统筹", "聚焦", "做好", "开展", "促")
_VAGUE_WORDS = ("有关", "相关", "若干", "适时", "大力")
_FORMAL_TYPES = frozenset({"通知", "请示", "报告", "函"})
_NON_OFFICIAL_TYPE_SUFFIXES: dict[str, tuple[str, ...]] = {
    "邮件": ("工作邮件", "职场邮件", "邮件"),
    "周报": ("工作周报", "周报"),
    "业务方案": ("业务方案", "商业方案", "实施方案", "方案"),
    "会议跟办": ("会议跟办清单", "会议跟办", "跟办清单"),
    "PPT提纲": ("PPT提纲", "演示提纲", "提纲"),
    "新闻稿": ("新闻稿", "新闻"),
    "公众号文章": ("公众号文章", "公众号长文", "文章"),
    "社交媒体文案": ("社交媒体文案", "社媒文案", "文案"),
    "短视频脚本": ("短视频脚本", "口播脚本", "脚本"),
    "文献综述": ("文献综述", "研究综述", "综述"),
    "研究提纲": ("研究提纲", "论文提纲", "提纲"),
    "摘要": ("结构化摘要", "研究摘要", "论文摘要", "摘要"),
    "审稿回复": ("逐条审稿回复", "审稿意见回复", "审稿回复", "审稿回应"),
}

type TitleStructure = Literal["single", "parallel", "subtitle"]


class StrictTitleModel(BaseModel):
    """Closed schema for the independent title-generation API."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class TitleScoreDimensions(StrictTitleModel):
    """Explainable zero-to-one-hundred title quality dimensions."""

    document_compliance: int = Field(ge=0, le=100)
    topic_relevance: int = Field(ge=0, le=100)
    information_density: int = Field(ge=0, le=100)
    rhythm: int = Field(ge=0, le=100)
    clarity: int = Field(ge=0, le=100)
    concision: int = Field(ge=0, le=100)
    action_orientation: int = Field(ge=0, le=100)
    factual_restraint: int = Field(ge=0, le=100)
    formula_fit: int = Field(ge=0, le=100)


class RankedTitleCandidate(StrictTitleModel):
    """One formula-backed title with ranking evidence."""

    title: str = Field(min_length=1, max_length=300)
    formula_id: str = Field(min_length=1, max_length=80)
    formula_name: str = Field(min_length=1, max_length=100)
    style: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=1_000)
    score: int = Field(ge=0, le=100)
    scores: TitleScoreDimensions
    rank: int = Field(ge=1, le=20)
    selected: bool = False


class TitleProposal(StrictTitleModel):
    """Unscored title proposal accepted from a strict live-model contract."""

    title: str = Field(min_length=1, max_length=300)
    formula_id: str = Field(min_length=1, max_length=80)
    formula_name: str = Field(min_length=1, max_length=100)
    style: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=500)


class TitleGenerationRequest(StrictTitleModel):
    """Inputs for generating and ranking titles before body drafting."""

    document_type: str = Field(default="工作总结", min_length=1, max_length=100)
    topic: str = Field(min_length=1, max_length=300)
    purpose: str = Field(default="", max_length=2_000)
    audience: str = Field(default="", max_length=500)
    materials: str | list[str] = Field(default="")
    tone: str = Field(default="稳健规范", max_length=100)
    reference_style: str = Field(default="权威媒体综合写法", max_length=100)
    style_references: list[StyleReference] = Field(default_factory=list, max_length=8)
    count: int = Field(default=5, ge=1, le=20)
    formula_ids: list[str] = Field(default_factory=list, max_length=12)
    custom_title_formula: CustomTitleFormula | str | None = None
    live: bool = False
    provider: ProviderSettings | None = None

    @field_validator("formula_ids")
    @classmethod
    def validate_formula_ids(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 80 for value in values):
            raise ValueError("formula_ids 必须是长度不超过80的非空字符串")
        if len(values) != len(set(values)):
            raise ValueError("formula_ids 不得重复")
        return values

    @model_validator(mode="after")
    def validate_live_settings(self) -> Self:
        if self.live and self.provider is None:
            raise ValueError("live=true 时必须提供 provider")
        return self

    def material_text(self) -> str:
        """Return material as one normalized block."""

        if isinstance(self.materials, str):
            return self.materials.strip()
        return "\n".join(item.strip() for item in self.materials if item.strip())


class TitleReferenceProfile(StrictTitleModel):
    """Aggregate structural traits extracted from selected article titles only."""

    sample_count: int = Field(ge=1, le=8)
    target_length: int = Field(ge=1, le=300)
    preferred_structure: Literal["single", "parallel", "subtitle"]
    average_segment_count: int = Field(ge=1, le=12)
    action_title_ratio: int = Field(ge=0, le=100)


class TitleGenerationResult(StrictTitleModel):
    """Ranked title batch and its deterministic scoring contract."""

    recommended_title: str = Field(min_length=1, max_length=300)
    candidates: list[RankedTitleCandidate] = Field(min_length=1, max_length=20)
    applied_formula_ids: tuple[str, ...]
    scoring_weights: dict[str, int]
    reference_profile: TitleReferenceProfile | None = None
    meta: GenerationMeta


_SCORING_WEIGHTS: dict[str, int] = {
    "document_compliance": 20,
    "topic_relevance": 20,
    "information_density": 5,
    "concision": 10,
    "rhythm": 5,
    "clarity": 8,
    "action_orientation": 2,
    "factual_restraint": 5,
    "formula_fit": 25,
}


def title_request_from_generate(request: GenerateRequest) -> TitleGenerationRequest:
    """Project a backwards-compatible full-draft request onto the title contract."""

    return TitleGenerationRequest(
        document_type=request.document_type,
        topic=request.topic,
        purpose=request.purpose,
        audience=request.audience,
        materials=request.materials,
        tone=request.tone,
        reference_style=request.reference_style,
        style_references=request.style_references,
        count=request.title_count,
        formula_ids=list(request.title_formula_ids),
        custom_title_formula=request.custom_title_formula,
        live=False,
    )


def generate_titles_demo(request: TitleGenerationRequest) -> TitleGenerationResult:
    """Generate, explain, score, and rank a repeatable title batch."""

    document_type = normalize_document_type(request.document_type)
    topic = clean_topic(request.topic)
    formulas = title_formulas_for(document_type, request.formula_ids)
    reference_profile = analyze_reference_titles(
        scenario_style_references(request.document_type, request.style_references)
    )
    raw_candidates: list[tuple[str, str, str, str, int]] = []
    custom = _custom_formula(request.custom_title_formula)
    if custom is not None:
        title = (
            _render_template(
                custom.template,
                topic=topic,
                document_type=document_type,
                purpose=request.purpose,
                audience=request.audience,
            )
            if custom.template
            else _apply_custom_rule(custom.rule, topic=topic, document_type=document_type)
        )
        reason = custom.rule or "按用户给定标题模板生成。"
        raw_candidates.append((title, "custom", custom.name, custom.style, 100))
        custom_reason = f"用户公式：{reason}"
    else:
        custom_reason = ""
    for formula in formulas:
        raw_candidates.append(
            (
                _render_formula(formula, request, topic, document_type),
                formula.id,
                formula.name,
                formula.style,
                formula.base_priority,
            )
        )
    reference_candidate = _reference_structure_candidate(
        reference_profile,
        document_type=document_type,
        topic=topic,
    )
    if reference_candidate is not None:
        insert_at = 2 if len(raw_candidates) >= 2 else len(raw_candidates)
        raw_candidates.insert(insert_at, reference_candidate)
    raw_candidates.extend(_derived_candidates(document_type, topic, request.count))

    unique: list[tuple[str, str, str, str, int]] = []
    seen: set[str] = set()
    for item in raw_candidates:
        title = _normalize_title(item[0])
        if not title or title in seen:
            continue
        seen.add(title)
        unique.append((title, *item[1:]))
        if len(unique) >= request.count:
            break
    if not unique:
        raise ValueError("没有生成可用标题，请检查标题公式")

    return rank_title_proposals(
        request,
        [
            TitleProposal(
                title=title,
                formula_id=formula_id,
                formula_name=formula_name,
                style=style,
                reason=(
                    custom_reason
                    if formula_id == "custom"
                    else _formula_principle(formulas, formula_id)
                ),
            )
            for title, formula_id, formula_name, style, _ in unique
        ],
        formula_priorities={item[1]: item[4] for item in unique},
        reference_profile=reference_profile,
        meta=GenerationMeta(mode="demo"),
    )


def rank_title_proposals(
    request: TitleGenerationRequest,
    proposals: list[TitleProposal],
    *,
    formula_priorities: Mapping[str, int] | None = None,
    reference_profile: TitleReferenceProfile | None = None,
    meta: GenerationMeta | None = None,
) -> TitleGenerationResult:
    """Apply the same deterministic scorer to local or model proposals."""

    if not proposals:
        raise ValueError("标题候选不得为空")
    document_type = normalize_document_type(request.document_type)
    topic = clean_topic(request.topic)
    priorities = formula_priorities or {}
    profile = reference_profile or analyze_reference_titles(
        scenario_style_references(request.document_type, request.style_references)
    )
    ranked_values: list[tuple[int, int, int, TitleProposal, TitleScoreDimensions]] = []
    seen: set[str] = set()
    for order, proposal in enumerate(proposals[: request.count]):
        title = _normalize_title(proposal.title)
        if not title or title in seen:
            continue
        seen.add(title)
        base_priority = max(0, min(100, priorities.get(proposal.formula_id, 80)))
        scores = score_title(
            title,
            topic=topic,
            document_type=document_type,
            materials=request.material_text(),
            formula_fit=base_priority,
            reference_profile=profile,
        )
        overall = _weighted_score(scores)
        ranked_values.append((overall, base_priority, -order, proposal, scores))
    if not ranked_values:
        raise ValueError("标题候选经去重后为空")
    ranked_values.sort(key=lambda value: (value[0], value[1], value[2]), reverse=True)

    candidates: list[RankedTitleCandidate] = []
    for rank, (score, _, _, proposal, scores) in enumerate(ranked_values, 1):
        reason = f"{proposal.reason} 综合评分 {score} 分，优势在于{_score_strength(scores)}。"
        candidates.append(
            RankedTitleCandidate(
                title=_normalize_title(proposal.title),
                formula_id=proposal.formula_id,
                formula_name=proposal.formula_name,
                style=proposal.style,
                reason=reason,
                score=score,
                scores=scores,
                rank=rank,
                selected=rank == 1,
            )
        )
    return TitleGenerationResult(
        recommended_title=candidates[0].title,
        candidates=candidates,
        applied_formula_ids=tuple(candidate.formula_id for candidate in candidates),
        scoring_weights=dict(_SCORING_WEIGHTS),
        reference_profile=profile,
        meta=meta or GenerationMeta(mode="demo"),
    )


def as_document_title_candidates(result: TitleGenerationResult) -> list[TitleCandidate]:
    """Map the richer title response onto the established draft response model."""

    return [
        TitleCandidate(
            title=candidate.title,
            style=candidate.style,
            reason=candidate.reason,
            selected=candidate.selected,
            formula_id=candidate.formula_id,
            formula_name=candidate.formula_name,
            score=candidate.score,
            score_dimensions=candidate.scores.model_dump(),
            rank=candidate.rank,
        )
        for candidate in result.candidates
    ]


def score_title(
    title: str,
    *,
    topic: str,
    document_type: str,
    materials: str,
    formula_fit: int = 80,
    reference_profile: TitleReferenceProfile | None = None,
) -> TitleScoreDimensions:
    """Score one title deterministically without model or network access."""

    normalized = _normalize_title(title)
    document_compliance = _document_compliance(normalized, document_type)
    topic_relevance = _topic_relevance(normalized, topic)
    information_density = _information_density(normalized, topic, document_type)
    clarity = max(
        20,
        100
        - 18 * sum(normalized.count(word) for word in _VAGUE_WORDS)
        - (28 if normalized.count("关于") > 1 else 0)
        - (12 if "  " in title else 0),
    )
    length = len(normalized.replace(" ", ""))
    ideal_min, ideal_max = (10, 34) if document_type in _FORMAL_TYPES else (8, 40)
    if reference_profile is not None:
        distance = abs(length - reference_profile.target_length)
        concision = max(35, 100 - distance * 4)
    elif ideal_min <= length <= ideal_max:
        concision = 100
    elif length < ideal_min:
        concision = max(45, 100 - (ideal_min - length) * 8)
    else:
        concision = max(30, 100 - (length - ideal_max) * 5)
    action_hits = sum(1 for word in _ACTION_WORDS if word in normalized)
    scene = scenario_for_document_type(document_type).id
    action_orientation = min(100, 55 + action_hits * 15) if scene == "gongwen" else 90
    rhythm = _rhythm_score(normalized, reference_profile) if scene == "gongwen" else 90
    if scene == "academic" and any(
        term in normalized for term in ("首次证明", "填补空白", "实干", "开新局")
    ):
        clarity = max(20, clarity - 30)
    material_numbers = set(_NUMBER.findall(materials))
    title_numbers = set(_NUMBER.findall(normalized))
    unsupported = title_numbers - material_numbers
    factual_restraint = 100 if not unsupported else max(20, 100 - len(unsupported) * 35)
    return TitleScoreDimensions(
        document_compliance=document_compliance,
        topic_relevance=topic_relevance,
        information_density=information_density,
        rhythm=rhythm,
        clarity=clarity,
        concision=concision,
        action_orientation=action_orientation,
        factual_restraint=factual_restraint,
        formula_fit=max(0, min(100, formula_fit)),
    )


def scenario_style_references(
    document_type: str, references: Iterable[StyleReference]
) -> list[StyleReference]:
    """Drop stale publication references when a task has moved to another scenario."""

    if scenario_for_document_type(document_type).id == "gongwen":
        return list(references)
    return [
        reference
        for reference in references
        if not any(
            name in reference.source_name
            for name in ("人民日报", "人民网", "光明日报", "光明网", "求是")
        )
    ]


def analyze_reference_titles(
    references: Iterable[StyleReference],
) -> TitleReferenceProfile | None:
    """Aggregate structure from selected titles without retaining their wording."""

    titles = [reference.title.strip() for reference in references if reference.title.strip()]
    if not titles:
        return None
    structures = [_title_structure(title) for title in titles]
    structure_order: tuple[TitleStructure, ...] = ("subtitle", "parallel", "single")
    preferred = max(
        structure_order,
        key=lambda name: (structures.count(name), -structure_order.index(name)),
    )
    segment_counts = [_segment_count(title) for title in titles]
    action_count = sum(any(word in title for word in _ACTION_WORDS) for title in titles)
    return TitleReferenceProfile(
        sample_count=len(titles),
        target_length=max(1, round(sum(len(title) for title in titles) / len(titles))),
        preferred_structure=preferred,
        average_segment_count=max(1, round(sum(segment_counts) / len(segment_counts))),
        action_title_ratio=round(action_count * 100 / len(titles)),
    )


def clean_topic(value: str) -> str:
    """Remove redundant title wrappers while retaining the substantive topic."""

    topic = value.strip().rstrip("。；，")
    for prefix in ("关于", "围绕"):
        if topic.startswith(prefix) and len(topic) > len(prefix) + 2:
            topic = topic[len(prefix) :]
    for suffix in (
        "的通知",
        "的请示",
        "的报告",
        "实施方案",
        "工作总结",
        "会议纪要",
        "汇报材料",
    ):
        if topic.endswith(suffix) and len(topic) > len(suffix) + 2:
            topic = topic[: -len(suffix)]
    return topic.strip()


def _custom_formula(value: CustomTitleFormula | str | None) -> CustomTitleFormula | None:
    if value is None:
        return None
    if isinstance(value, CustomTitleFormula):
        return value
    if _PLACEHOLDER.search(value):
        return CustomTitleFormula(template=value)
    return CustomTitleFormula(rule=value)


def _apply_custom_rule(rule: str, *, topic: str, document_type: str) -> str:
    """Apply a bounded offline interpretation of a user-provided title rule."""

    scene = scenario_for_document_type(document_type).id
    if scene != "gongwen":
        if any(label in rule for label in ("主副", "破折号", "副标题")):
            return f"{topic}——{document_type}"
        if any(label in rule for label in ("对仗", "并列", "两句")):
            suffix = "梳理证据 明确边界" if scene == "academic" else "说明现状 明确下一步"
            return f"{topic}：{suffix}"
        return f"{topic}：{document_type}"
    if any(label in rule for label in ("主副", "破折号", "副标题")):
        return f"实干担当促提升——{topic}"
    if any(label in rule for label in ("对仗", "并列", "两句")):
        return f"聚焦{topic} 强化责任落实"
    if any(label in rule for label in ("行动", "动词", "部署", "有力")):
        if document_type in _FORMAL_TYPES:
            return f"关于扎实推进{topic}工作的{document_type}"
        return f"扎实推进{topic}落地见效"
    if document_type in _FORMAL_TYPES:
        return f"关于{topic}的{document_type}"
    if document_type == "会议纪要":
        return f"{topic}会议纪要"
    if document_type == "讲话稿":
        return f"在{topic}会议上的讲话"
    if document_type == "汇报材料":
        return f"关于{topic}的汇报"
    return f"{topic}{document_type}"


def _render_formula(
    formula: TitleFormulaDefinition,
    request: TitleGenerationRequest,
    topic: str,
    document_type: str,
) -> str:
    template = formula.template
    if scenario_for_document_type(document_type).id != "gongwen":
        suffixes = _NON_OFFICIAL_TYPE_SUFFIXES.get(document_type, (document_type,))
        if topic.endswith(suffixes) and "{topic}" in template:
            prefix, _, suffix = template.partition("{topic}")
            appended_type = suffix.replace("{document_type}", document_type)
            appended_type = appended_type.strip(" ：:｜|—-").removeprefix("的")
            if appended_type in suffixes:
                # Keep the user's complete topic; omit only the redundant formula tag.
                # Custom formulas never enter this path and remain literal user choices.
                template = prefix + "{topic}"
    return _render_template(
        template,
        topic=topic,
        document_type=document_type,
        purpose=request.purpose,
        audience=request.audience,
    )


def _render_template(
    template: str,
    *,
    topic: str,
    document_type: str,
    purpose: str,
    audience: str,
) -> str:
    values = {
        "topic": topic,
        "document_type": document_type,
        "purpose": purpose.strip(),
        "audience": audience.strip(),
    }
    rendered = _PLACEHOLDER.sub(lambda match: values[match.group(1)], template.strip()).rstrip(
        "：｜ "
    )
    unknown = _UNKNOWN_PLACEHOLDER.search(rendered)
    if unknown:
        raise ValueError(f"标题公式含未知变量：{unknown.group(0)}")
    if not rendered:
        raise ValueError("标题公式生成结果为空")
    return rendered


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().rstrip("。；，"))


def _derived_candidates(
    document_type: str,
    topic: str,
    needed: int,
) -> list[tuple[str, str, str, str, int]]:
    if needed <= 0:
        return []
    templates: tuple[str, ...]
    scene = scenario_for_document_type(document_type).id
    if scene == "academic":
        templates = (
            "{topic}：研究范围与证据",
            "{topic}的概念与方法",
            "{topic}：问题与讨论",
            "{topic}研究的证据边界",
            "{topic}：已有材料与待解问题",
        )
    elif scene != "gongwen":
        templates = (
            "{topic}：重点信息",
            "{topic}的背景与要点",
            "{topic}：现状与后续",
            "关于{topic}的沟通要点",
            "{topic}：信息与判断",
        )
    elif document_type in _FORMAL_TYPES:
        templates = (
            "关于深入推进{topic}的{document_type}",
            "关于有序推进{topic}工作的{document_type}",
            "关于做好{topic}重点任务的{document_type}",
            "关于协同推进{topic}的{document_type}",
            "关于健全{topic}工作机制的{document_type}",
            "关于提升{topic}工作质效的{document_type}",
            "关于细化落实{topic}任务的{document_type}",
            "关于推动{topic}取得实效的{document_type}",
            "关于统筹开展{topic}的{document_type}",
            "关于持续深化{topic}的{document_type}",
        )
    elif document_type == "会议纪要":
        templates = (
            "{topic}任务部署会议纪要",
            "{topic}工作协调会纪要",
            "研究{topic}有关事项会议纪要",
            "{topic}专题调度会议纪要",
            "{topic}会商会议纪要",
        )
    else:
        templates = (
            "锚定目标抓落实 推动{topic}取得实效",
            "聚力攻坚提质效 扎实推进{topic}",
            "系统谋划 精准施策 推动{topic}走深走实",
            "凝心聚力担使命 实干笃行促{topic}",
            "突出重点 强化协同 全面提升{topic}工作质效",
            "坚持问题导向 推动{topic}取得新进展",
            "以闭环管理促进{topic}提质增效",
            "抓统筹 强执行 促提升——{topic}",
            "立足实际谋发展 聚焦{topic}开新局",
            "围绕主线精准发力 推动{topic}落地见效",
        )
    result: list[tuple[str, str, str, str, int]] = []
    for index, template in enumerate(templates[:needed], 1):
        rendered = template.format(topic=topic, document_type=document_type)
        result.append((rendered, f"derived-{index}", "扩展变化式", "扩展备选", 65 - index))
    return result


def _reference_structure_candidate(
    profile: TitleReferenceProfile | None,
    *,
    document_type: str,
    topic: str,
) -> tuple[str, str, str, str, int] | None:
    if profile is None:
        return None
    scene = scenario_for_document_type(document_type).id
    if scene == "academic":
        title = f"{topic}：研究范围、证据与讨论"
    elif scene != "gongwen":
        title = (
            f"{topic}：背景与要点"
            if profile.preferred_structure == "single"
            else f"{topic}——重点信息与后续"
        )
    elif document_type in _FORMAL_TYPES:
        if profile.preferred_structure == "parallel":
            title = f"关于统筹推进{topic}并强化责任落实的{document_type}"
        else:
            title = f"关于推动{topic}提质增效的{document_type}"
    elif document_type == "会议纪要":
        title = f"研究推进{topic}重点任务会议纪要"
    elif profile.preferred_structure == "subtitle":
        title = f"凝心聚力抓落实 实干担当促提升——{topic}"
    elif profile.preferred_structure == "parallel":
        title = f"聚焦{topic} 强化责任落实"
    else:
        title = f"推动{topic}提质增效"
    return (
        title,
        "reference-structure",
        "文章来源结构提炼式",
        "结构借鉴",
        90,
    )


def _document_compliance(title: str, document_type: str) -> int:
    if document_type in _FORMAL_TYPES:
        score = 100 if title.endswith(document_type) else 45
        if not title.startswith("关于"):
            score -= 12
        return max(0, score)
    if document_type == "会议纪要":
        return 100 if title.endswith(("会议纪要", "会纪要")) else 55
    if document_type == "工作总结":
        return 100 if title.endswith("工作总结") else 88
    if document_type == "实施方案":
        return 100 if title.endswith("实施方案") else 88
    if document_type == "讲话稿":
        return 100 if title.startswith("在") and title.endswith("讲话") else 88
    if document_type == "汇报材料":
        return 100 if title.endswith(("汇报", "汇报材料")) else 88
    return 100 if title.strip() else 0


def _topic_relevance(title: str, topic: str) -> int:
    compact_title = re.sub(r"\s+", "", title)
    compact_topic = re.sub(r"\s+", "", topic)
    if compact_topic and compact_topic in compact_title:
        return 100
    topic_chars = set(compact_topic)
    if not topic_chars:
        return 0
    overlap = len(topic_chars & set(compact_title)) / len(topic_chars)
    return max(20, min(95, round(overlap * 100)))


def _information_density(title: str, topic: str, document_type: str) -> int:
    compact = re.sub(r"[\s，。；：—-]+", "", title)
    topic_compact = re.sub(r"\s+", "", topic)
    signals = int(bool(topic_compact and topic_compact in compact))
    signals += int(document_type in compact)
    if scenario_for_document_type(document_type).id == "gongwen":
        signals += min(2, sum(1 for word in _ACTION_WORDS if word in compact))
    else:
        signals += int(any(mark in title for mark in ("：", "｜", "——")))
        signals += int(bool(compact))
    vague_penalty = 8 * sum(compact.count(word) for word in _VAGUE_WORDS)
    length_penalty = max(0, len(compact) - 42) * 2
    return max(25, min(100, 48 + signals * 13 - vague_penalty - length_penalty))


def _rhythm_score(
    title: str,
    profile: TitleReferenceProfile | None,
) -> int:
    structure = _title_structure(title)
    if structure == "subtitle":
        score = 94
    elif structure == "parallel":
        segments = [segment for segment in re.split(r"[ ，、；：]+", title) if segment]
        lengths = [len(segment) for segment in segments]
        score = 92 if lengths and max(lengths) - min(lengths) <= 4 else 78
    else:
        score = 82
    if profile is not None:
        score += 6 if structure == profile.preferred_structure else -5
        score -= min(12, abs(_segment_count(title) - profile.average_segment_count) * 3)
    return max(20, min(100, score))


def _title_structure(title: str) -> TitleStructure:
    if "——" in title or "--" in title:
        return "subtitle"
    if len([part for part in re.split(r"[ ，、；：]+", title) if part]) >= 2:
        return "parallel"
    return "single"


def _segment_count(title: str) -> int:
    if "——" in title:
        return max(1, len([part for part in title.split("——") if part.strip()]))
    return max(1, len([part for part in re.split(r"[ ，、；：]+", title) if part]))


def _weighted_score(scores: TitleScoreDimensions) -> int:
    values: Mapping[str, int] = scores.model_dump()
    weighted = sum(values[name] * weight for name, weight in _SCORING_WEIGHTS.items())
    return max(0, min(100, round(weighted / 100)))


def _formula_principle(
    formulas: Iterable[TitleFormulaDefinition],
    formula_id: str,
) -> str:
    for formula in formulas:
        if formula.id == formula_id:
            return formula.principle
    return "在预置公式基础上扩展标题表达。"


def _score_strength(scores: TitleScoreDimensions) -> str:
    labels = {
        "document_compliance": "文种规范",
        "topic_relevance": "主题相关",
        "information_density": "信息密度",
        "rhythm": "节奏辨识",
        "clarity": "表达清晰",
        "concision": "简洁凝练",
        "action_orientation": "行动导向",
        "factual_restraint": "事实稳健",
        "formula_fit": "公式适配",
    }
    values: Mapping[str, int] = scores.model_dump()
    strongest = sorted(values, key=lambda key: (-values[key], key))[:2]
    return "、".join(labels[key] for key in strongest)


__all__ = [
    "RankedTitleCandidate",
    "StrictTitleModel",
    "TitleGenerationRequest",
    "TitleGenerationResult",
    "TitleProposal",
    "TitleReferenceProfile",
    "TitleScoreDimensions",
    "analyze_reference_titles",
    "as_document_title_candidates",
    "clean_topic",
    "generate_titles_demo",
    "rank_title_proposals",
    "score_title",
    "title_request_from_generate",
]
