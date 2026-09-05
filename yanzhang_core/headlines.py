"""Deterministic generation and scoring for high-value entry sentences."""

# Chinese candidate text intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from yanzhang_core.models import CoreModel, WritingBrief
from yanzhang_core.packs import HeadlineKind
from yanzhang_core.scenario_profiles import get_scenario_profile

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


class CandidateFactContext(CoreModel):
    """One bounded factual material excerpt available to candidate scoring."""

    material_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    excerpt: str = Field(min_length=1, max_length=4_000)


class CandidateRequest(CoreModel):
    """Inputs for title, opening, section-heading, or topic-sentence work."""

    brief: WritingBrief
    kind: HeadlineKind = "title"
    section_topic: str = Field(default="", max_length=300)
    count: int = Field(default=5, ge=1, le=12)
    required_terms: tuple[str, ...] = Field(default=(), max_length=16)
    formula_ids: tuple[str, ...] = Field(default=(), max_length=20)
    fact_contexts: tuple[CandidateFactContext, ...] = Field(default=(), max_length=16)

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

    @field_validator("fact_contexts")
    @classmethod
    def validate_unique_fact_contexts(
        cls,
        values: tuple[CandidateFactContext, ...],
    ) -> tuple[CandidateFactContext, ...]:
        material_ids = tuple(value.material_id for value in values)
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("fact_contexts 的资料标识不得重复")
        return values


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


# Formula identifiers remain stable across clients; the actual templates and
# explanations belong to the selected scenario, not to a universal official style.
_SCENE_TEMPLATES: dict[str, dict[HeadlineKind, tuple[tuple[str, str], ...]]] = {
    "workplace": {
        "title": (
            ("事项直述", "{topic}"),
            ("目的前置", "{topic}：{goal}"),
            ("结论与说明", "{focus}的现状与选择——{topic}"),
            ("三项重点", "进展、风险与下一步——{topic}"),
            ("四项信息", "目标、进度、依赖、交付——{topic}"),
            ("现状与选择", "从当前情况到下一步选择——{topic}"),
            ("问题到方案", "从{focus}到解决方案：{topic}"),
            ("四项议程", "一看进展、二查风险、三明依赖、四定安排——{topic}"),
            ("请求确认", "请确认：{topic}的下一步安排"),
            ("决策问题", "{topic}：需要作出什么选择"),
            ("收件对象", "发给{audience}：{topic}"),
            ("交付类型", "{topic}｜{content_type}"),
            ("快速同步", "{focus}进展同步"),
        ),
        "opening": (
            ("目的直述", "围绕{topic}，本次沟通希望{goal}。"),
            ("三项速览", "关于{topic}，先同步进展，再说明风险，最后确认下一步。"),
            ("四项速览", "{topic}的沟通包括四项：目标、当前进展、协作依赖与待确认事项。"),
            ("状态与需求", "关于{topic}，既说明目前的情况，也明确还需要哪些支持。"),
            ("先后顺序", "先交代{focus}的现状，再比较可选路径，最后讨论{goal}。"),
            ("收件人切入", "{audience}，您好。本次同步{topic}的相关信息，希望{goal}。"),
            ("问题切入", "关于{topic}，当前需要回答的问题是：{goal}。"),
            ("重点取舍", "讨论{topic}，先把影响{focus}的关键信息说清楚。"),
            ("信息边界", "以下围绕{topic}区分已确认信息、尚存风险与待确认安排。"),
            ("简短同步", "本次沟通聚焦{focus}，目标是{goal}。"),
        ),
        "section_heading": (
            ("主题直述", "{focus}"),
            ("三项检查", "{focus}：进展、风险与选择"),
            ("四项检查", "{focus}：目标、状态、依赖与交付"),
            ("现状与需求", "{focus}的当前情况与协作需求"),
            ("问题与路径", "从{focus}的问题到解决路径"),
            ("决策焦点", "{focus}：需要确认的事项"),
            ("下一步", "{focus}的下一步安排"),
            ("阻塞问题", "影响{focus}的主要阻塞"),
            ("方案比较", "{focus}的可选方案与取舍"),
            ("协作约定", "{focus}的协作方式与验收标准"),
        ),
        "topic_sentence": (
            ("直接统领", "本段围绕{focus}展开，重点说明{goal}。"),
            ("三项判断", "讨论{focus}，需要同步已知进展、说明现实风险、确认下一步选择。"),
            ("四项信息", "关于{focus}，目标、状态、依赖与交付应分别说明。"),
            ("情况与需求", "{focus}既需要清楚的现状说明，也需要明确的协作请求。"),
            ("问题到选择", "围绕{focus}，先明确问题，再比较路径，最后确认选择。"),
            ("判断边界", "对{focus}的判断应基于已确认的信息，而非默认假设。"),
            ("证据先行", "分析{focus}，应回到实际记录和可核对的信息。"),
            ("读者需要", "向{audience}说明{focus}，应优先呈现与本次决定有关的信息。"),
            ("过渡到请求", "说明当前情况后，以下列出{focus}仍需确认的事项。"),
            ("突出重点", "关于{topic}，比罗列过程更重要的是讲清{focus}的状态与影响。"),
        ),
    },
    "academic": {
        "title": (
            ("研究主题", "{topic}"),
            ("问题与目标", "{topic}：{goal}"),
            ("主题与文体", "{topic}——{content_type}"),
            ("三维综述", "{topic}：概念、方法与证据"),
            ("四维综述", "{topic}：问题、理论、方法与边界"),
            ("共识与分歧", "{topic}研究的共识与分歧"),
            ("研究脉络", "{topic}：从问题界定到证据比较"),
            ("四维评述", "{topic}的四个分析维度：概念、理论、方法与证据"),
            ("问题聚焦", "{topic}中的{focus}问题"),
            ("研究设问", "如何理解{topic}：问题与分析路径"),
            ("研究视角", "{topic}的研究视角与适用范围"),
            ("规范文体", "{topic}：{content_type}"),
            ("主题评述", "{focus}研究述评"),
        ),
        "opening": (
            ("问题界定", "本文聚焦{topic}，拟回答{goal}，并明确相关概念与材料边界。"),
            ("三层综述", "讨论{topic}，需厘清概念界定、比较研究方法、审视证据强度。"),
            ("四层框架", "围绕{topic}，本文分别考察研究问题、理论视角、资料方法与解释边界。"),
            ("比较视角", "分析{topic}，既要比较已有研究的共同认识，也要辨析结论分歧的条件。"),
            ("论证路径", "本文由{focus}的问题界定进入证据比较，再讨论{topic}的解释范围。"),
            ("研究定位", "为讨论{topic}，本文先明确研究问题与分析范围，再梳理相关证据。"),
            ("研究问题", "{topic}中哪些问题已有证据支持，哪些判断仍有待检验？"),
            ("方法差异", "理解{topic}的研究差异，需要区分概念、资料与方法上的不同。"),
            (
                "材料边界",
                "本文关于{topic}的讨论仅基于已提供的研究材料，文献覆盖与证据强度仍需核查。",
            ),
            ("简明定位", "本文以{topic}为讨论对象，重点考察{focus}。"),
        ),
        "section_heading": (
            ("研究焦点", "{focus}"),
            ("概念方法证据", "{focus}：概念、方法与证据"),
            ("四维比较", "{focus}：问题、理论、资料与解释"),
            ("共识与争论", "{focus}的共识与争论"),
            ("分析路径", "从{focus}的界定到证据比较"),
            ("证据范围", "{focus}：已有认识及其边界"),
            ("方法考察", "{focus}的研究方法与适用条件"),
            ("未决问题", "{focus}中仍待回答的问题"),
            ("解释比较", "{focus}的不同解释路径"),
            ("理论关系", "{focus}的理论关系与可检验命题"),
        ),
        "topic_sentence": (
            ("问题统领", "本段考察{focus}，重点区分相关主张及其证据依据。"),
            ("三项比较", "对{focus}的比较应同时考察概念口径、研究方法与证据强度。"),
            ("四项边界", "讨论{focus}时，研究对象、资料来源、分析方法与适用范围需要分别说明。"),
            ("条件判断", "关于{focus}的结论既取决于资料条件，也受到研究设计的约束。"),
            ("论证递进", "对{focus}的论证应从概念界定进入证据分析，再讨论解释边界。"),
            ("判断审慎", "对{focus}的判断需要与可核查的研究依据相对应。"),
            ("证据核对", "关于{focus}的每项文献主张，均需回查实际来源及相关页段。"),
            ("解释深度", "呈现{focus}时，应明确术语含义、证据条件与尚存的不确定性。"),
            ("论证过渡", "在界定研究问题后，以下进一步考察{focus}的相关证据。"),
            ("分歧定位", "与其概括性地罗列{topic}研究，更需要辨析{focus}的证据差异。"),
        ),
    },
    "media": {
        "title": (
            ("主题直述", "{topic}"),
            ("读者价值", "{topic}：{goal}"),
            ("焦点与背景", "看懂{focus}——{topic}"),
            ("三项看点", "事件、背景与影响——{topic}"),
            ("四项看点", "事实、细节、背景与疑问——{topic}"),
            ("表象与背景", "{topic}：现象之外，还有哪些背景"),
            ("信息路径", "从{focus}出发，看懂{topic}"),
            ("四问导读", "{topic}四问：发生什么、为何关注、依据何在、如何理解"),
            ("读者焦点", "关于{topic}，值得了解的信息"),
            ("解释问题", "{topic}，究竟该怎么看"),
            ("受众导读", "给{audience}的{topic}导读"),
            ("内容类型", "{topic}｜{content_type}"),
            ("简洁焦点", "看懂{focus}"),
        ),
        "opening": (
            ("信息直述", "关于{topic}，先说明与{audience}最相关的信息。"),
            ("三层展开", "{topic}发生了什么、有哪些背景、该如何理解？先从已知事实说起。"),
            ("四项导读", "读懂{topic}，不妨分开看事实、细节、背景与尚待解答的问题。"),
            ("事实与解读", "谈{topic}，既要说清发生了什么，也要分清哪些是对事实的解释。"),
            ("层层展开", "先了解{focus}，再补充相关背景，最后讨论{topic}意味着什么。"),
            ("读者切入", "如果你也关注{topic}，可以先从{focus}这个问题看起。"),
            ("问题切入", "关于{topic}，{audience}最需要知道什么？"),
            ("信息取舍", "比给{topic}贴上标签更重要的，是把{focus}的来龙去脉说清楚。"),
            ("事实边界", "以下围绕{topic}整理已知信息，并将事实、引述和观点分别标明。"),
            ("短句开场", "今天聊{topic}，先把{focus}说清楚。"),
        ),
        "section_heading": (
            ("焦点直述", "{focus}"),
            ("三层看点", "{focus}：事实、背景与影响"),
            ("四层信息", "{focus}：主体、过程、背景与疑问"),
            ("信息与解读", "{focus}：已知信息与不同解读"),
            ("前因后果", "从{focus}看相关背景"),
            ("解释焦点", "{focus}：值得了解的细节"),
            ("读者提示", "关于{focus}，先看这些信息"),
            ("读者疑问", "关于{focus}，还有什么待解答"),
            ("理解路径", "理解{focus}的几个角度"),
            ("背景解释", "{focus}背后的运作方式"),
        ),
        "topic_sentence": (
            ("焦点统领", "谈到{focus}，先区分已知信息与尚待核实的细节。"),
            ("三层展开", "理解{focus}，要看具体事实、补齐相关背景、分辨不同观点。"),
            ("四项信息", "围绕{focus}，主体、经过、背景与信息来源需要交代清楚。"),
            ("细节与全貌", "介绍{focus}，既要给出必要细节，也要保留理解全貌的背景。"),
            ("叙事顺序", "从{focus}的已知信息出发，再逐步展开背景与解释。"),
            ("读者重点", "关于{focus}，值得关注的是它与读者具体问题之间的联系。"),
            ("信息溯源", "{focus}的事实描述与直接引语应分别标明可核对的来源。"),
            ("受众关联", "向{audience}介绍{focus}，应先说明与其相关的具体信息。"),
            ("叙事过渡", "了解基本情况后，再来看{focus}有哪些值得补充的背景。"),
            ("避免标签", "相比概括性地评价{topic}，把{focus}的具体情况讲清楚更有帮助。"),
        ),
    },
}


def _scenario_formulas(kind: HeadlineKind, pack_id: str) -> tuple[HeadlineFormula, ...]:
    profile = get_scenario_profile(pack_id)
    templates = _SCENE_TEMPLATES.get(profile.id, {}).get(kind)
    if templates is None:
        return _FORMULAS[kind]
    return tuple(
        formula.model_copy(
            update={
                "name": name,
                "template": template,
                "rationale": (
                    f"按{profile.name}组织{name}，以实际材料支撑表达，不预设成果或补造事实。"
                ),
            }
        )
        for formula, (name, template) in zip(_FORMULAS[kind], templates, strict=True)
    )


def generate_candidates(request: CandidateRequest) -> CandidateBatch:
    """Generate, score, and rank a repeatable candidate batch offline."""

    context = _template_context(request)
    generated: list[tuple[int, int, str, HeadlineFormula, CandidateScores]] = []
    seen: set[str] = set()
    selected_ids = set(request.formula_ids)
    formulas = (
        formula
        for formula in _scenario_formulas(request.kind, request.brief.scenario_pack_id)
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


def list_headline_formulas(
    kind: HeadlineKind | None = None, *, scenario_pack_id: str | None = None
) -> tuple[HeadlineFormula, ...]:
    """List the stable formula catalog, optionally scoped to one expression kind."""

    if scenario_pack_id is None:
        if kind is not None:
            return _FORMULAS[kind]
        return tuple(formula for formulas in _FORMULAS.values() for formula in formulas)
    kinds: tuple[HeadlineKind, ...] = (kind,) if kind else tuple(_FORMULAS)
    return tuple(
        formula for item in kinds for formula in _scenario_formulas(item, scenario_pack_id)
    )


def score_candidate(text: str, request: CandidateRequest) -> CandidateScores:
    """Score user- or engine-supplied entry text using the same local contract."""

    value = _normalize_text(text)
    topic = _context_topic(request)
    terms = (
        topic,
        *request.brief.keywords,
        *request.required_terms,
    )
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
    if request.brief.scenario_pack_id == "academic":
        # Academic fit comes from careful propositions, not addressing the
        # audience by name or rewarding an official-speech cadence.
        audience_fit = 92
        rhythm = 90 if len(segments) <= 4 else 75
        if any(term in value for term in ("压实责任", "提高站位", "促落实", "开新局", "政治站位")):
            audience_fit = 30
            channel_fit = min(channel_fit, 30)
        if any(term in value for term in ("首次证明", "填补空白", "彻底解决", "颠覆性")):
            channel_fit = min(channel_fit, 45)
    elif request.brief.scenario_pack_id in {"workplace", "media"}:
        if any(term in value for term in ("提高政治站位", "压实政治责任", "熔铸于魂")):
            audience_fit = 40
            channel_fit = min(channel_fit, 40)
    factual_restraint = 100
    source_text = " ".join(
        (
            request.brief.title,
            request.brief.selected_title or "",
            request.brief.goal,
            *request.brief.constraints,
            *request.brief.keywords,
            *(section.title for section in request.brief.structure_override),
            *(section.purpose for section in request.brief.structure_override),
            *(context.title for context in request.fact_contexts),
            *(context.excerpt for context in request.fact_contexts),
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
    focus = _context_focus(request)
    return {
        "topic": _context_topic(request),
        "goal": brief.goal.rstrip("。！？"),
        "audience": brief.audience,
        "content_type": brief.content_type,
        "focus": focus,
    }


def _context_topic(request: CandidateRequest) -> str:
    """Keep title alternatives neutral while grounding later expressions in the adopted title."""

    if request.kind != "title" and request.brief.selected_title:
        return request.brief.selected_title
    return request.brief.title


def _context_focus(request: CandidateRequest) -> str:
    """Resolve the strongest explicit focus before using conservative fallbacks."""

    brief = request.brief
    if request.section_topic:
        return request.section_topic
    if brief.keywords:
        return brief.keywords[0]
    if brief.structure_override:
        return brief.structure_override[0].title
    if brief.selected_title and request.kind != "title":
        return brief.selected_title
    if request.fact_contexts:
        return request.fact_contexts[0].title
    return brief.title


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
    "CandidateFactContext",
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
