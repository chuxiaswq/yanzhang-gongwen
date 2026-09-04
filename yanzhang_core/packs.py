"""Built-in scenario packs and high-frequency writing recipes."""

# Chinese catalog copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from yanzhang_core.models import Channel, CoreModel

type ScenarioPackId = Literal["gongwen", "workplace", "media", "academic"]
type HeadlineKind = Literal["title", "opening", "section_heading", "topic_sentence"]


class RecipeSection(CoreModel):
    """One ordered semantic slot within a reusable writing recipe."""

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=500)
    required: bool = True


class RecipeDefinition(CoreModel):
    """A transparent, inspectable recipe for one recurring writing task."""

    id: str = Field(min_length=1, max_length=100)
    pack_id: ScenarioPackId
    name: str = Field(min_length=1, max_length=100)
    content_type: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=500)
    channels: tuple[Channel, ...] = Field(min_length=1, max_length=8)
    required_inputs: tuple[str, ...] = Field(min_length=1, max_length=20)
    sections: tuple[RecipeSection, ...] = Field(min_length=1, max_length=24)
    default_headline_kind: HeadlineKind = "title"
    output_formats: tuple[str, ...] = Field(default=("docx", "markdown", "text"))
    fact_strategy: str = Field(min_length=1, max_length=500)

    @field_validator("required_inputs", "output_formats")
    @classmethod
    def validate_unique_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("配方列表字段不得包含空值")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("配方列表字段不得重复")
        return cleaned

    @model_validator(mode="after")
    def validate_sections(self) -> Self:
        ids = tuple(section.id for section in self.sections)
        if len(ids) != len(set(ids)):
            raise ValueError("配方 section id 不得重复")
        return self


class ScenarioPack(CoreModel):
    """One discoverable domain bundle with related task recipes."""

    id: ScenarioPackId
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    audiences: tuple[str, ...] = Field(min_length=1, max_length=20)
    recipes: tuple[RecipeDefinition, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_recipes(self) -> Self:
        ids = tuple(recipe.id for recipe in self.recipes)
        if len(ids) != len(set(ids)):
            raise ValueError("场景包 recipe id 不得重复")
        if any(recipe.pack_id != self.id for recipe in self.recipes):
            raise ValueError("场景包与配方的 pack_id 必须一致")
        return self


def _section(id_: str, title: str, purpose: str, *, required: bool = True) -> RecipeSection:
    return RecipeSection(id=id_, title=title, purpose=purpose, required=required)


def _recipe(
    id_: str,
    pack_id: ScenarioPackId,
    name: str,
    content_type: str,
    summary: str,
    channels: tuple[Channel, ...],
    required_inputs: tuple[str, ...],
    sections: tuple[RecipeSection, ...],
    fact_strategy: str,
    *,
    headline_kind: HeadlineKind = "title",
    output_formats: tuple[str, ...] = ("docx", "markdown", "text"),
) -> RecipeDefinition:
    return RecipeDefinition(
        id=id_,
        pack_id=pack_id,
        name=name,
        content_type=content_type,
        summary=summary,
        channels=channels,
        required_inputs=required_inputs,
        sections=sections,
        default_headline_kind=headline_kind,
        output_formats=output_formats,
        fact_strategy=fact_strategy,
    )


GONGWEN_PACK = ScenarioPack(
    id="gongwen",
    name="公文与综合材料",
    description="面向政企事业单位综合文字岗位的规范成稿、部署和复盘任务。",
    audiences=("办公室", "行政", "党建", "研究", "管理人员"),
    recipes=(
        _recipe(
            "work-summary",
            "gongwen",
            "工作总结",
            "工作总结",
            "以回顾、成效、问题和提升形成完整复盘。",
            ("document",),
            ("工作范围", "事实材料", "时间范围"),
            (
                _section("overview", "总体情况", "交代背景、范围和总体判断。"),
                _section("results", "主要成效", "按事实归纳进展和成果。"),
                _section("problems", "问题不足", "识别短板及其影响。"),
                _section("next", "下一步安排", "明确改进方向和行动。"),
            ),
            "数字、日期、名称和成果仅使用已关联材料；缺少依据时保留待补标记。",
        ),
        _recipe(
            "briefing-material",
            "gongwen",
            "汇报材料",
            "汇报材料",
            "按进展、亮点、问题和计划组织面向决策者的汇报。",
            ("document", "presentation"),
            ("汇报对象", "事项进展", "关键数据"),
            (
                _section("progress", "工作进展", "先给结论，再说明总体进度。"),
                _section("highlights", "亮点成效", "选择有证据的代表性成果。"),
                _section("issues", "困难问题", "区分现象、原因和影响。"),
                _section("plan", "工作计划", "给出任务、责任和节点。"),
            ),
            "关键结论应绑定来源，推测性判断须明确标记。",
        ),
        _recipe(
            "leadership-speech",
            "gongwen",
            "领导讲话",
            "讲话稿",
            "以凝聚共识、部署重点和压实责任组织正式讲话。",
            ("document",),
            ("讲话主题", "听众", "事实材料"),
            (
                _section("consensus", "提高站位，凝聚思想共识", "阐明意义和形势。"),
                _section("priorities", "突出重点，推动任务落实", "部署重点任务和工作方法。"),
                _section("responsibility", "压实责任，确保取得实效", "提出责任、作风和实效要求。"),
            ),
            "事实用于支撑判断和部署，不把写法参考中的数据带入讲话。",
        ),
        _recipe(
            "research-report",
            "gongwen",
            "调研报告",
            "调研报告",
            "按调研范围、现状证据、问题成因和对策建议形成研究型报告。",
            ("document",),
            ("调研主题", "调研范围", "事实材料"),
            (
                _section("scope", "调研概况", "说明背景、对象、范围和方法边界。"),
                _section("findings", "现状与成效", "基于材料归纳现状、做法和成效。"),
                _section("issues", "问题与原因", "区分问题表现、影响和原因。"),
                _section("recommendations", "对策建议", "提出与问题对应的可执行建议。"),
            ),
            "调研事实、数字和因果判断须有材料依据；建议与问题逐项对应。",
        ),
        _recipe(
            "implementation-plan",
            "gongwen",
            "实施方案",
            "实施方案",
            "从总体要求到任务、步骤和保障形成执行路线图。",
            ("document",),
            ("工作目标", "重点任务", "实施条件"),
            (
                _section("requirements", "总体要求", "明确依据、原则和方向。"),
                _section("goals", "工作目标", "定义可验证的目标状态。"),
                _section("actions", "重点举措", "展开任务、责任和协同关系。"),
                _section("schedule", "实施步骤", "明确阶段、节点和交付物。"),
                _section("safeguards", "保障措施", "配置组织、资源和监督机制。"),
            ),
            "目标值、时间节点和责任主体必须来自已确认材料。",
        ),
        _recipe(
            "meeting-minutes",
            "gongwen",
            "会议纪要",
            "会议纪要",
            "把会议过程压缩为议定事项、责任分工和执行要求。",
            ("meeting", "document"),
            ("会议记录", "参会信息", "议题"),
            (
                _section("meeting", "会议情况", "记录时间、主题和必要参会信息。"),
                _section("decisions", "议定事项", "提炼明确结论和决策。"),
                _section("owners", "责任分工", "关联责任人、期限和依赖。"),
                _section("followup", "落实要求", "形成可跟踪的后续动作。"),
            ),
            "人名、时间、决策和任务状态逐项回查会议原始材料。",
        ),
    ),
)


WORKPLACE_PACK = ScenarioPack(
    id="workplace",
    name="职场沟通",
    description="覆盖日常协作、进度同步、方案沟通和会议跟办。",
    audiences=("项目经理", "行政", "人力资源", "销售支持", "管理者"),
    recipes=(
        _recipe(
            "work-email",
            "workplace",
            "工作邮件",
            "邮件",
            "用清晰主题、结论前置和明确行动降低沟通成本。",
            ("email",),
            ("收件对象", "沟通目的", "必要事实"),
            (
                _section("subject", "邮件主题", "让收件人快速识别事项和动作。"),
                _section("context", "背景与结论", "用最少文字交代背景和核心结论。"),
                _section("details", "必要信息", "提供决策或执行所需事实。"),
                _section("action", "下一步", "明确请求、责任与时间。"),
            ),
            "不得补写材料中未提供的承诺、期限或责任主体。",
        ),
        _recipe(
            "weekly-report",
            "workplace",
            "周报",
            "周报",
            "按完成、进展、风险和下周计划快速同步工作。",
            ("document", "email"),
            ("本周记录", "项目状态", "下周安排"),
            (
                _section("done", "本周完成", "列出已产生的成果。"),
                _section("progress", "进行中", "说明进度和下一节点。"),
                _section("risks", "风险与协同", "暴露阻塞及所需支持。", required=False),
                _section("next", "下周计划", "列出优先级和交付物。"),
            ),
            "完成状态和进度数字以工作记录为准。",
        ),
        _recipe(
            "business-proposal",
            "workplace",
            "业务方案",
            "业务方案",
            "从问题、目标、方案、收益和风险构建决策材料。",
            ("document", "presentation"),
            ("业务问题", "目标受众", "约束条件"),
            (
                _section("problem", "问题与机会", "界定需要解决的业务问题。"),
                _section("goal", "目标与原则", "说明成功标准和边界。"),
                _section("solution", "方案设计", "描述路径、资源和关键动作。"),
                _section("value", "预期价值", "说明收益及其计算依据。"),
                _section("risk", "风险与推进", "给出风险、应对和实施节奏。"),
            ),
            "收益数字、市场判断和比较结论应关联证据。",
        ),
        _recipe(
            "meeting-followup",
            "workplace",
            "会议跟办清单",
            "会议跟办",
            "把讨论结果转化为责任明确、时间清晰的行动清单。",
            ("meeting", "email"),
            ("会议记录", "参会人员", "议题"),
            (
                _section("decisions", "会议结论", "只保留已经确认的决定。"),
                _section("actions", "行动项", "拆出动作、负责人、期限和状态。"),
                _section("dependencies", "依赖与风险", "标记协同关系和阻塞。", required=False),
                _section("confirm", "待确认事项", "集中呈现尚需确认的信息。", required=False),
            ),
            "行动项必须能在会议记录中定位；模糊责任以待确认为状态。",
        ),
        _recipe(
            "presentation-outline",
            "workplace",
            "PPT提纲",
            "PPT提纲",
            "把母稿压缩为结论先行、逐页单一重点的演示结构。",
            ("presentation",),
            ("汇报主题", "目标听众", "时间或页数"),
            (
                _section("message", "核心结论", "用一句话明确演示希望听众记住什么。"),
                _section("storyline", "叙事主线", "按问题、洞察和行动安排信息顺序。"),
                _section("slides", "逐页提纲", "为每页设置结论式标题与三项以内要点。"),
                _section("close", "收束与行动", "明确决策请求或下一步。"),
            ),
            "图表数字和结论均关联母稿或资料来源，缺少依据时保留待补标记。",
            output_formats=("markdown", "text"),
        ),
    ),
)


MEDIA_PACK = ScenarioPack(
    id="media",
    name="内容传播",
    description="把可信底稿转化为新闻、公众号、社交媒体和短视频文字成果。",
    audiences=("宣传", "品牌", "市场", "新媒体", "内容运营"),
    recipes=(
        _recipe(
            "press-release",
            "media",
            "新闻稿",
            "新闻稿",
            "用标题、导语、主体和背景信息讲清事件价值。",
            ("web", "document"),
            ("新闻事实", "发布对象", "时间地点"),
            (
                _section("headline", "标题", "准确呈现最重要的新闻事实。"),
                _section("lead", "导语", "集中交代核心事实和意义。"),
                _section("body", "主体", "按重要程度补充事实与引述。"),
                _section("background", "背景", "提供理解事件所需上下文。", required=False),
            ),
            "新闻六要素、数字、引语和机构名称逐项绑定来源。",
        ),
        _recipe(
            "wechat-article",
            "media",
            "公众号文章",
            "公众号文章",
            "以清晰价值主张、场景化展开和行动收束形成长文。",
            ("web",),
            ("主题", "目标读者", "核心材料"),
            (
                _section("hook", "标题与开场", "建立与读者相关的阅读理由。"),
                _section("context", "问题场景", "呈现背景、矛盾或机会。"),
                _section("value", "核心内容", "按层次展开事实与观点。"),
                _section("close", "总结与行动", "回扣价值并给出下一步。"),
            ),
            "事实与观点分开表达；引用和数字关联可追溯材料。",
        ),
        _recipe(
            "social-post",
            "media",
            "社交媒体文案",
            "社交媒体文案",
            "用单一焦点、简短价值和自然行动提示完成短文。",
            ("social",),
            ("发布目的", "目标读者", "核心信息"),
            (
                _section("hook", "开场", "在首句给出最相关的信息。"),
                _section("message", "正文", "只保留一个核心观点和必要事实。"),
                _section("action", "收束", "自然邀请读者了解、反馈或行动。"),
            ),
            "不用未经材料支持的极限词、数字或效果承诺。",
            headline_kind="opening",
            output_formats=("text", "markdown"),
        ),
        _recipe(
            "short-video-script",
            "media",
            "短视频脚本",
            "短视频脚本",
            "按钩子、信息推进、转折和行动设计口播文字。",
            ("social",),
            ("视频主题", "受众", "目标时长"),
            (
                _section("hook", "开场钩子", "快速建立问题或价值期待。"),
                _section("beats", "内容节拍", "按口播节奏逐步推进信息。"),
                _section("turn", "关键转折", "突出核心认识或解决路径。"),
                _section("cta", "行动提示", "用自然语言给出下一步。"),
            ),
            "案例、数据和效果表述必须来自已确认材料。",
            headline_kind="opening",
            output_formats=("text", "markdown"),
        ),
    ),
)


ACADEMIC_PACK = ScenarioPack(
    id="academic",
    name="学术与研究写作",
    description="支持研究问题梳理、证据组织和规范表达，不替代领域审阅。",
    audiences=("研究人员", "教师", "学生", "政策研究", "行业分析师"),
    recipes=(
        _recipe(
            "literature-review",
            "academic",
            "文献综述",
            "文献综述",
            "围绕研究问题组织主题、分歧、证据和研究空白。",
            ("academic", "document"),
            ("研究问题", "文献材料", "引用规范"),
            (
                _section("scope", "问题与范围", "界定问题、概念和材料范围。"),
                _section("themes", "主题脉络", "按主题而非逐篇罗列组织研究。"),
                _section("debate", "证据与分歧", "比较结论、方法与证据强度。"),
                _section("gap", "研究空白", "从已有证据推导仍待回答的问题。"),
            ),
            "每项文献主张必须关联实际导入的来源和定位信息。",
            output_formats=("docx", "markdown", "text"),
        ),
        _recipe(
            "research-outline",
            "academic",
            "研究提纲",
            "研究提纲",
            "从研究问题、概念、方法到分析路径形成可执行提纲。",
            ("academic", "document"),
            ("研究主题", "研究问题", "资料范围"),
            (
                _section("question", "研究问题", "形成明确、可回答的问题。"),
                _section("framework", "分析框架", "定义概念、变量和关系。"),
                _section("method", "资料与方法", "说明数据、样本和分析方法。"),
                _section("chapters", "章节结构", "让每章服务于研究问题。"),
            ),
            "方法和资料能力按用户提供条件陈述，不虚构数据可得性。",
        ),
        _recipe(
            "research-abstract",
            "academic",
            "研究摘要",
            "摘要",
            "用背景、方法、结果和结论压缩完整研究。",
            ("academic",),
            ("研究全文或结构化要点", "目标字数"),
            (
                _section("background", "背景与目的", "说明问题及研究目的。"),
                _section("method", "方法", "概括数据和研究设计。"),
                _section("result", "结果", "准确呈现关键发现。"),
                _section("conclusion", "结论", "说明意义、边界和启示。"),
            ),
            "摘要中的方法、结果和数字必须与原文一致。",
        ),
        _recipe(
            "reviewer-response",
            "academic",
            "审稿意见回复",
            "审稿回复",
            "逐条回应意见，说明修改、依据和稿件位置。",
            ("academic", "email"),
            ("审稿意见", "修改稿", "修改位置"),
            (
                _section("thanks", "总体说明", "简要致谢并说明修改原则。"),
                _section("responses", "逐条回复", "复述问题、给出回应和依据。"),
                _section("changes", "修改定位", "明确页码、段落或章节位置。"),
                _section("open", "保留意见", "对未采纳事项给出可核查说明。", required=False),
            ),
            "修改说明必须与实际稿件一致，引用应指向真实来源。",
        ),
    ),
)


SCENARIO_PACKS: tuple[ScenarioPack, ...] = (
    GONGWEN_PACK,
    WORKPLACE_PACK,
    MEDIA_PACK,
    ACADEMIC_PACK,
)


def list_scenario_packs() -> tuple[ScenarioPack, ...]:
    """Return the immutable built-in scenario catalog."""

    return SCENARIO_PACKS


def get_scenario_pack(pack_id: str) -> ScenarioPack:
    """Resolve a built-in scenario pack by stable id."""

    for pack in SCENARIO_PACKS:
        if pack.id == pack_id:
            return pack
    raise ValueError(f"未知场景包：{pack_id}")


def list_recipes(pack_id: str | None = None) -> tuple[RecipeDefinition, ...]:
    """List every recipe or only recipes belonging to one scenario pack."""

    packs = SCENARIO_PACKS if pack_id is None else (get_scenario_pack(pack_id),)
    return tuple(recipe for pack in packs for recipe in pack.recipes)


def get_recipe(recipe_id: str, *, pack_id: str | None = None) -> RecipeDefinition:
    """Resolve a globally unique recipe id with an optional pack guard."""

    matches = tuple(recipe for recipe in list_recipes(pack_id) if recipe.id == recipe_id)
    if not matches:
        raise ValueError(f"未知写作配方：{recipe_id}")
    return matches[0]


__all__ = [
    "ACADEMIC_PACK",
    "GONGWEN_PACK",
    "MEDIA_PACK",
    "SCENARIO_PACKS",
    "WORKPLACE_PACK",
    "HeadlineKind",
    "RecipeDefinition",
    "RecipeSection",
    "ScenarioPack",
    "ScenarioPackId",
    "get_recipe",
    "get_scenario_pack",
    "list_recipes",
    "list_scenario_packs",
]
