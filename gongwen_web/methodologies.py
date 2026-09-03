"""Typed title-formula and content-methodology catalog for official writing.

The catalog is deliberately deterministic and contains no source-article text.
It describes reusable writing structures that can be consumed by the local
engine, exposed by the HTTP API, or embedded in a provider prompt.
"""

# Chinese punctuation is intentional in public catalog copy.
# ruff: noqa: RUF001

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_NUMBERED_HEADING = re.compile(r"^(?:[一二三四五六七八九十]{1,3}|\d{1,2})[、.]\s*")


class CatalogModel(BaseModel):
    """Closed, immutable schema used by methodology catalog responses."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CustomTitleFormula(CatalogModel):
    """User-supplied title template or compact natural-language rule."""

    name: str = Field(default="用户自定义公式", min_length=1, max_length=100)
    template: str = Field(default="", max_length=300)
    rule: str = Field(default="", max_length=500)
    style: str = Field(default="自定义", min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_template_or_rule(self) -> CustomTitleFormula:
        if not self.template and not self.rule:
            raise ValueError("自定义标题公式至少需要 template 或 rule")
        return self


class CustomContentMethodology(CatalogModel):
    """User-defined content method with an explicit ordered step list."""

    name: str = Field(default="用户自定义方法论", min_length=1, max_length=100)
    summary: str = Field(default="按用户给定步骤组织正文。", min_length=1, max_length=500)
    logic: str = Field(default="依次展开用户给定步骤。", min_length=1, max_length=1_000)
    steps: tuple[str, ...] = Field(min_length=1, max_length=16)
    fact_strategy: str = Field(
        default="具体名称、数字、日期和政策信息仅使用用户材料。",
        min_length=1,
        max_length=500,
    )

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, steps: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(step.strip() for step in steps)
        if any(not step or len(step) > 200 for step in cleaned):
            raise ValueError("自定义方法论步骤必须是长度不超过200的非空文本")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("自定义方法论步骤不得重复")
        return cleaned


class TitleFormulaDefinition(CatalogModel):
    """One reusable formula for constructing an official-document title."""

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    applicable_document_types: tuple[str, ...]
    template: str = Field(min_length=1, max_length=300)
    style: str = Field(min_length=1, max_length=80)
    principle: str = Field(min_length=1, max_length=500)
    base_priority: int = Field(ge=0, le=100)


class ContentMethodologyDefinition(CatalogModel):
    """One section-by-section method for constructing a complete document."""

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    applicable_document_types: tuple[str, ...]
    summary: str = Field(min_length=1, max_length=500)
    logic: str = Field(min_length=1, max_length=500)
    headings: tuple[str, ...] = Field(min_length=1, max_length=16)
    section_purposes: tuple[str, ...] = Field(min_length=1, max_length=16)
    fact_strategy: str = Field(min_length=1, max_length=500)


class AppliedContentMethodology(CatalogModel):
    """Resolved built-in or user-defined method applied to one generation."""

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=500)
    logic: str = Field(min_length=1, max_length=1_000)
    headings: tuple[str, ...] = Field(min_length=1, max_length=16)
    section_purposes: tuple[str, ...] = Field(min_length=1, max_length=16)
    fact_strategy: str = Field(min_length=1, max_length=500)
    source: Literal["catalog", "custom"] = "catalog"


class MethodologyCatalog(CatalogModel):
    """Discoverable title and body-writing methods for API clients."""

    document_type: str | None = None
    title_formulas: tuple[TitleFormulaDefinition, ...]
    content_methodologies: tuple[ContentMethodologyDefinition, ...]
    default_title_formula_ids: tuple[str, ...]
    default_content_methodology_id: str
    title_scoring_dimensions: tuple[str, ...] = (
        "文种规范",
        "主题相关",
        "信息密度",
        "节奏辨识",
        "表达清晰",
        "简洁凝练",
        "行动导向",
        "事实稳健",
        "公式适配",
    )


_FORMAL_TYPES = ("通知", "请示", "报告", "函")
_MATERIAL_TYPES = ("工作总结", "实施方案", "讲话稿", "汇报材料")
_ALL_TYPES = (*_FORMAL_TYPES, "会议纪要", *_MATERIAL_TYPES)


TITLE_FORMULAS: tuple[TitleFormulaDefinition, ...] = (
    TitleFormulaDefinition(
        id="generic-elements",
        name="通用要素式",
        applicable_document_types=("*",),
        template="关于{topic}的{document_type}",
        style="通用规范",
        principle="以主题和材料类型构成清晰、可检索的通用标题。",
        base_priority=95,
    ),
    TitleFormulaDefinition(
        id="formal-elements",
        name="要素完整式",
        applicable_document_types=_FORMAL_TYPES,
        template="关于{topic}的{document_type}",
        style="要素完整",
        principle="以“关于＋事由＋文种”确保标题适合正式流转。",
        base_priority=100,
    ),
    TitleFormulaDefinition(
        id="formal-action",
        name="行动部署式",
        applicable_document_types=_FORMAL_TYPES,
        template="关于扎实推进{topic}工作的{document_type}",
        style="执行导向",
        principle="在完整文种要素基础上加入明确行动动词。",
        base_priority=91,
    ),
    TitleFormulaDefinition(
        id="formal-continuity",
        name="延续深化式",
        applicable_document_types=_FORMAL_TYPES,
        template="关于进一步做好{topic}有关工作的{document_type}",
        style="稳健规范",
        principle="适合对既有工作作延续、深化或再部署。",
        base_priority=86,
    ),
    TitleFormulaDefinition(
        id="formal-coordination",
        name="统筹协同式",
        applicable_document_types=_FORMAL_TYPES,
        template="关于加强{topic}工作统筹的{document_type}",
        style="协同推进",
        principle="突出跨部门统筹、协同和责任衔接。",
        base_priority=82,
    ),
    TitleFormulaDefinition(
        id="formal-focus",
        name="事项聚焦式",
        applicable_document_types=_FORMAL_TYPES,
        template="关于{topic}重点事项的{document_type}",
        style="重点聚焦",
        principle="压缩主题范围，适合围绕具体事项行文。",
        base_priority=79,
    ),
    TitleFormulaDefinition(
        id="minutes-standard",
        name="会议主题式",
        applicable_document_types=("会议纪要",),
        template="{topic}会议纪要",
        style="标准纪要",
        principle="直接标明会议主题和纪要文种。",
        base_priority=100,
    ),
    TitleFormulaDefinition(
        id="minutes-special",
        name="专题聚焦式",
        applicable_document_types=("会议纪要",),
        template="{topic}专题会议纪要",
        style="专题聚焦",
        principle="适合围绕单项议题形成的会议纪要。",
        base_priority=90,
    ),
    TitleFormulaDefinition(
        id="minutes-progress",
        name="推进部署式",
        applicable_document_types=("会议纪要",),
        template="{topic}工作推进会会议纪要",
        style="推进部署",
        principle="突出会议的任务分工与推进属性。",
        base_priority=85,
    ),
    TitleFormulaDefinition(
        id="minutes-study",
        name="研究事项式",
        applicable_document_types=("会议纪要",),
        template="研究推进{topic}工作会议纪要",
        style="事项明确",
        principle="突出会议研究、审议和推动的具体事项。",
        base_priority=82,
    ),
    TitleFormulaDefinition(
        id="minutes-coordination",
        name="协调办理式",
        applicable_document_types=("会议纪要",),
        template="{topic}协调会议纪要",
        style="协同办理",
        principle="适合跨部门协调、会商和联办事项。",
        base_priority=78,
    ),
    TitleFormulaDefinition(
        id="summary-standard",
        name="总结归档式",
        applicable_document_types=("工作总结",),
        template="{topic}工作总结",
        style="稳健规范",
        principle="直接呈现总结对象和材料类型，便于归档检索。",
        base_priority=100,
    ),
    TitleFormulaDefinition(
        id="plan-standard",
        name="方案归档式",
        applicable_document_types=("实施方案",),
        template="{topic}实施方案",
        style="稳健规范",
        principle="直接呈现实施事项和方案类型。",
        base_priority=100,
    ),
    TitleFormulaDefinition(
        id="speech-standard",
        name="讲话场景式",
        applicable_document_types=("讲话稿",),
        template="在{topic}会议上的讲话",
        style="场景明确",
        principle="明确讲话所处会议场景，保持称谓规范。",
        base_priority=100,
    ),
    TitleFormulaDefinition(
        id="briefing-standard",
        name="汇报事项式",
        applicable_document_types=("汇报材料",),
        template="关于{topic}的汇报",
        style="稳健规范",
        principle="以“关于＋事项＋汇报”明确汇报主题。",
        base_priority=100,
    ),
    TitleFormulaDefinition(
        id="material-outcome",
        name="主题成效式",
        applicable_document_types=_MATERIAL_TYPES,
        template="聚焦重点任务 推动{topic}提质增效",
        style="凝练概括",
        principle="以主题主线连接行动和预期成效。",
        base_priority=88,
    ),
    TitleFormulaDefinition(
        id="material-execution",
        name="实干结果式",
        applicable_document_types=_MATERIAL_TYPES,
        template="以实干实绩推动{topic}落地见效",
        style="部署有力",
        principle="用行动与结果构成递进关系。",
        base_priority=85,
    ),
    TitleFormulaDefinition(
        id="material-parallel",
        name="并列对仗式",
        applicable_document_types=_MATERIAL_TYPES,
        template="抓重点 破难点 推动{topic}取得新成效",
        style="并列对仗",
        principle="以前两项并列动作引出主题成果。",
        base_priority=82,
    ),
    TitleFormulaDefinition(
        id="material-subtitle",
        name="主副标题式",
        applicable_document_types=_MATERIAL_TYPES,
        template="守正创新促提升 实干担当开新局——{topic}",
        style="主副标题",
        principle="以概括性主标题配合具体主题副标题。",
        base_priority=78,
    ),
)


CONTENT_METHODOLOGIES: tuple[ContentMethodologyDefinition, ...] = (
    ContentMethodologyDefinition(
        id="notice-task-chain",
        name="目标—任务—保障闭环",
        applicable_document_types=("通知",),
        summary="先统一目标，再拆解任务，最后落实责任与保障。",
        logic="为什么做 → 做什么 → 谁来做、如何保障",
        headings=("一、明确总体要求", "二、聚焦重点任务", "三、强化组织保障"),
        section_purposes=(
            "说明背景、目的和总体标准",
            "分解重点任务、节点和责任",
            "明确协同、督导和闭环机制",
        ),
        fact_strategy="材料事实优先进入任务章节，时间和责任信息进入任务或保障章节。",
    ),
    ContentMethodologyDefinition(
        id="request-case-decision",
        name="情况—考虑—事项请示法",
        applicable_document_types=("请示",),
        summary="以客观情况为起点，充分说明考虑，集中提出需决策事项。",
        logic="事实背景 → 理由依据 → 单一明确请求",
        headings=("一、基本情况", "二、主要考虑", "三、请示事项"),
        section_purposes=("交代缘由和现状", "说明必要性、依据和可行性", "明确请示内容与决策点"),
        fact_strategy="事实和数据放入情况章节，请示事项不得超出材料和写作目的。",
    ),
    ContentMethodologyDefinition(
        id="report-progress-loop",
        name="情况—成效—问题—安排复盘法",
        applicable_document_types=("报告",),
        summary="完整呈现进展、成效、问题和后续安排。",
        logic="总体判断 → 证据成效 → 差距诊断 → 下一步闭环",
        headings=("一、总体情况", "二、主要做法与成效", "三、存在问题", "四、下一步安排"),
        section_purposes=(
            "概括工作全貌",
            "用事实说明做法和成效",
            "客观识别短板",
            "提出有节点的后续安排",
        ),
        fact_strategy="数字事实优先支撑成效，问题句进入问题章节，计划和日期进入下一步章节。",
    ),
    ContentMethodologyDefinition(
        id="letter-context-request",
        name="情况—商洽—办理法",
        applicable_document_types=("函",),
        summary="简明交代情况，集中表达商洽事项，给出办理建议。",
        logic="说明来由 → 提出事项 → 明确反馈方式",
        headings=("一、有关情况", "二、商洽事项", "三、办理建议"),
        section_purposes=("说明联系背景", "列明协商或请求事项", "提出办理、回复和衔接建议"),
        fact_strategy="只保留与商洽事项直接相关的事实、主体和时限。",
    ),
    ContentMethodologyDefinition(
        id="minutes-decision-accountability",
        name="会情—议定—落实纪要法",
        applicable_document_types=("会议纪要",),
        summary="压缩过程叙述，突出会议结论、责任主体和落实节点。",
        logic="会议基本信息 → 明确议定事项 → 责任与时限",
        headings=("一、会议基本情况", "二、议定事项", "三、落实要求"),
        section_purposes=("记录必要会议信息", "逐项归纳会议结论", "明确责任、节点和督办方式"),
        fact_strategy="不得把未形成结论的讨论写成议定事项；责任和日期须有材料依据。",
    ),
    ContentMethodologyDefinition(
        id="summary-review-improve",
        name="回顾—成效—问题—提升法",
        applicable_document_types=("工作总结",),
        summary="由总体回顾进入成效证据，再以问题诊断承接下一步提升。",
        logic="总体回顾 → 做法与证据 → 问题诊断 → 改进计划",
        headings=("一、总体情况", "二、主要做法和成效", "三、问题与不足", "四、下一步工作"),
        section_purposes=(
            "形成阶段性判断",
            "归纳做法并用数据支撑",
            "客观查摆问题",
            "提出针对性改进举措",
        ),
        fact_strategy="成效、问题和计划分别匹配材料中的数字句、问题句和计划句。",
    ),
    ContentMethodologyDefinition(
        id="plan-goal-roadmap",
        name="要求—目标—举措—步骤—保障路线图",
        applicable_document_types=("实施方案",),
        summary="把目标转化为可执行举措、阶段步骤和保障机制。",
        logic="总体原则 → 可检验目标 → 重点举措 → 时间路线 → 保障闭环",
        headings=("一、总体要求", "二、目标任务", "三、重点举措", "四、实施步骤", "五、保障措施"),
        section_purposes=(
            "明确指导思想和原则",
            "定义成果目标",
            "拆分工作抓手",
            "安排阶段节点",
            "落实组织、资源和督导",
        ),
        fact_strategy="已有任务、责任和时限进入对应章节；缺失的具体值使用待补占位。",
    ),
    ContentMethodologyDefinition(
        id="speech-consensus-action",
        name="共识—重点—责任动员法",
        applicable_document_types=("讲话稿",),
        summary="先凝聚认识，再部署重点，最后以责任要求收束。",
        logic="统一认识 → 明确怎么干 → 压实谁来干",
        headings=(
            "一、提高站位，凝聚思想共识",
            "二、突出重点，推动任务落实",
            "三、压实责任，确保取得实效",
        ),
        section_purposes=("阐明意义和形势", "部署重点任务和工作方法", "提出责任、作风和实效要求"),
        fact_strategy="事实用于支撑判断和部署，不把写法参考中的数据带入讲话。",
    ),
    ContentMethodologyDefinition(
        id="briefing-progress-problem-plan",
        name="进展—亮点—短板—计划汇报法",
        applicable_document_types=("汇报材料",),
        summary="先报进度，再提炼特色做法，客观呈现短板并提出下步考虑。",
        logic="进展证据 → 方法亮点 → 问题短板 → 资源或行动诉求",
        headings=("一、工作进展", "二、特色做法", "三、短板问题", "四、下步考虑"),
        section_purposes=("说明任务进展", "提炼可复用做法", "呈现关键问题", "提出计划与需协调事项"),
        fact_strategy="进度数字与具体做法优先，问题和计划必须在材料中找到对应表述。",
    ),
    ContentMethodologyDefinition(
        id="universal-problem-solving",
        name="现状—问题—对策—保障分析法",
        applicable_document_types=(*_ALL_TYPES, "*"),
        summary="适合问题导向明显的综合材料，以诊断推动解决方案落地。",
        logic="描述现状 → 定位问题 → 提出对策 → 建立保障",
        headings=("一、总体情况", "二、主要问题", "三、重点举措", "四、保障机制"),
        section_purposes=(
            "概括事实背景",
            "归纳材料所示问题",
            "提出针对性措施",
            "明确责任和反馈闭环",
        ),
        fact_strategy="问题章节只引用材料已有问题，具体数字和时限不作推断。",
    ),
)


_DEFAULT_TITLE_FORMULAS: dict[str, tuple[str, ...]] = {
    **{
        document_type: (
            "formal-elements",
            "formal-action",
            "formal-continuity",
            "formal-coordination",
            "formal-focus",
        )
        for document_type in _FORMAL_TYPES
    },
    "会议纪要": (
        "minutes-standard",
        "minutes-special",
        "minutes-progress",
        "minutes-study",
        "minutes-coordination",
    ),
    "工作总结": (
        "summary-standard",
        "material-outcome",
        "material-execution",
        "material-parallel",
        "material-subtitle",
    ),
    "实施方案": (
        "plan-standard",
        "material-outcome",
        "material-execution",
        "material-parallel",
        "material-subtitle",
    ),
    "讲话稿": (
        "speech-standard",
        "material-outcome",
        "material-execution",
        "material-parallel",
        "material-subtitle",
    ),
    "汇报材料": (
        "briefing-standard",
        "material-outcome",
        "material-execution",
        "material-parallel",
        "material-subtitle",
    ),
}

_DEFAULT_CONTENT_METHODOLOGY: dict[str, str] = {
    "通知": "notice-task-chain",
    "请示": "request-case-decision",
    "报告": "report-progress-loop",
    "函": "letter-context-request",
    "会议纪要": "minutes-decision-accountability",
    "工作总结": "summary-review-improve",
    "实施方案": "plan-goal-roadmap",
    "讲话稿": "speech-consensus-action",
    "汇报材料": "briefing-progress-problem-plan",
}


def normalize_document_type(value: str) -> str:
    """Normalize common UI aliases without rejecting future custom types."""

    normalized = value.strip()
    aliases = {
        "纪要": "会议纪要",
        "总结": "工作总结",
        "方案": "实施方案",
        "讲话": "讲话稿",
        "汇报": "汇报材料",
    }
    return aliases.get(normalized, normalized)


def title_formula(formula_id: str) -> TitleFormulaDefinition:
    """Resolve one formula id or raise a user-facing validation error."""

    normalized = formula_id.strip()
    for formula in TITLE_FORMULAS:
        if formula.id == normalized:
            return formula
    raise ValueError(f"未知标题公式：{normalized or '（空）'}")


def title_formulas_for(
    document_type: str,
    requested_ids: Iterable[str] = (),
) -> tuple[TitleFormulaDefinition, ...]:
    """Return applicable formulas in deterministic request/default order."""

    normalized_type = normalize_document_type(document_type)
    ids = tuple(value.strip() for value in requested_ids if value.strip())
    if not ids:
        ids = _DEFAULT_TITLE_FORMULAS.get(
            normalized_type,
            ("generic-elements",),
        )
    formulas: list[TitleFormulaDefinition] = []
    for formula_id in ids:
        formula = title_formula(formula_id)
        if (
            normalized_type not in formula.applicable_document_types
            and "*" not in formula.applicable_document_types
        ):
            raise ValueError(f"标题公式 {formula.id} 不适用于文种“{normalized_type}”")
        if formula not in formulas:
            formulas.append(formula)
    return tuple(formulas)


def default_title_formula_ids(document_type: str) -> tuple[str, ...]:
    """Return the ordered built-in title formulas for a document type."""

    normalized = normalize_document_type(document_type)
    return _DEFAULT_TITLE_FORMULAS.get(normalized, ("generic-elements",))


def content_methodology(methodology_id: str) -> ContentMethodologyDefinition:
    """Resolve one content method id or raise a user-facing validation error."""

    normalized = methodology_id.strip()
    for methodology in CONTENT_METHODOLOGIES:
        if methodology.id == normalized:
            return methodology
    raise ValueError(f"未知内容方法论：{normalized or '（空）'}")


def default_content_methodology_id(document_type: str) -> str:
    """Return the default method id for the normalized document type."""

    normalized = normalize_document_type(document_type)
    return _DEFAULT_CONTENT_METHODOLOGY.get(normalized, "universal-problem-solving")


def resolve_content_methodology(
    document_type: str,
    methodology_id: str | None = None,
    *,
    custom: CustomContentMethodology | None = None,
) -> AppliedContentMethodology:
    """Resolve and validate a built-in content method for one document type."""

    normalized_type = normalize_document_type(document_type)
    if custom is not None:
        headings = tuple(
            _numbered_heading(index, step) for index, step in enumerate(custom.steps, 1)
        )
        purposes = tuple(step.strip() for step in custom.steps)
        return AppliedContentMethodology(
            id="custom",
            name=custom.name,
            summary=custom.summary,
            logic=custom.logic,
            headings=headings,
            section_purposes=purposes,
            fact_strategy=custom.fact_strategy,
            source="custom",
        )
    selected_id = (
        methodology_id.strip()
        if methodology_id
        else default_content_methodology_id(normalized_type)
    )
    methodology = content_methodology(selected_id)
    if (
        normalized_type not in methodology.applicable_document_types
        and "*" not in methodology.applicable_document_types
    ):
        raise ValueError(f"内容方法论 {selected_id} 不适用于文种“{normalized_type}”")
    return AppliedContentMethodology(
        id=methodology.id,
        name=methodology.name,
        summary=methodology.summary,
        logic=methodology.logic,
        headings=methodology.headings,
        section_purposes=methodology.section_purposes,
        fact_strategy=methodology.fact_strategy,
    )


def _numbered_heading(index: int, step: str) -> str:
    cleaned = step.strip()
    if not cleaned:
        raise ValueError("自定义方法论步骤不得为空")
    if _NUMBERED_HEADING.match(cleaned):
        return cleaned
    numerals = (
        "一",
        "二",
        "三",
        "四",
        "五",
        "六",
        "七",
        "八",
        "九",
        "十",
        "十一",
        "十二",
        "十三",
        "十四",
        "十五",
        "十六",
    )
    return f"{numerals[index - 1]}、{cleaned}"


def methodology_catalog(document_type: str | None = None) -> MethodologyCatalog:
    """Build a complete or document-type-filtered discovery response."""

    normalized_type = normalize_document_type(document_type) if document_type else None
    formulas = tuple(
        formula
        for formula in TITLE_FORMULAS
        if normalized_type is None
        or normalized_type in formula.applicable_document_types
        or "*" in formula.applicable_document_types
    )
    methods = tuple(
        method
        for method in CONTENT_METHODOLOGIES
        if normalized_type is None
        or normalized_type in method.applicable_document_types
        or "*" in method.applicable_document_types
    )
    return MethodologyCatalog(
        document_type=normalized_type,
        title_formulas=formulas,
        content_methodologies=methods,
        default_title_formula_ids=(
            default_title_formula_ids(normalized_type) if normalized_type is not None else ()
        ),
        default_content_methodology_id=(default_content_methodology_id(normalized_type or "")),
    )


__all__ = [
    "CONTENT_METHODOLOGIES",
    "TITLE_FORMULAS",
    "AppliedContentMethodology",
    "ContentMethodologyDefinition",
    "CustomContentMethodology",
    "CustomTitleFormula",
    "MethodologyCatalog",
    "TitleFormulaDefinition",
    "content_methodology",
    "default_content_methodology_id",
    "default_title_formula_ids",
    "methodology_catalog",
    "normalize_document_type",
    "resolve_content_methodology",
    "title_formula",
    "title_formulas_for",
]
