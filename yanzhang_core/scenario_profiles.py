"""Single source of truth for scenario-aware writing UI and prompt guidance.

The style descriptions are original structural guidance, not fetched examples or
claims that a publisher's source text has been retrieved. Recipes remain owned
by :mod:`yanzhang_core.packs`; this catalog only serializes that registry.
"""

# Chinese catalog copy intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from yanzhang_core.packs import ScenarioPackId, list_scenario_packs

type ProfileText = Annotated[str, Field(min_length=1, max_length=2_000)]


class _ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ScenarioStyle(_ProfileModel):
    """One inspectable writing method, identified independently of its label."""

    id: ProfileText
    label: ProfileText
    description: ProfileText


class ScenarioSource(_ProfileModel):
    """Describe where this scenario gets evidence, not an implied search result."""

    title: ProfileText
    description: ProfileText
    action_label: ProfileText
    action: Literal["articles", "materials", "academic"]


class ScenarioLabels(_ProfileModel):
    """The common writing fields with scenario-specific language."""

    topic: ProfileText
    purpose: ProfileText
    audience: ProfileText
    materials: ProfileText
    requirements: ProfileText
    keywords: ProfileText
    generate: ProfileText
    review: ProfileText
    reference_style: ProfileText


class ScenarioExample(_ProfileModel):
    """Public synthetic starter content, never private workspace information."""

    topic: ProfileText
    purpose: ProfileText
    audience: ProfileText
    materials: ProfileText
    requirements: ProfileText
    keywords: ProfileText


class ScenarioProfile(_ProfileModel):
    """Scenario-specific UI, evidence, review and model-prompt contract."""

    id: ScenarioPackId
    name: ProfileText
    description: ProfileText
    styles: tuple[ScenarioStyle, ...] = Field(min_length=1)
    tones: tuple[ProfileText, ...] = Field(min_length=1)
    default_style: ProfileText
    default_tone: ProfileText
    recipe_styles: dict[str, str] = Field(min_length=1)
    source: ScenarioSource
    labels: ScenarioLabels
    placeholders: ScenarioLabels
    checklist: tuple[ProfileText, ...] = Field(min_length=6, max_length=6)
    review_dimensions: tuple[ProfileText, ...] = Field(min_length=4, max_length=4)
    example: ScenarioExample
    prompt_guidance: tuple[ProfileText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_choices(self) -> Self:
        style_ids = [style.id for style in self.styles]
        style_labels = [style.label for style in self.styles]
        if len(style_ids) != len(set(style_ids)):
            raise ValueError("写法标识须唯一")
        if len(style_labels) != len(set(style_labels)):
            raise ValueError("写法名称须唯一")
        if self.default_style not in style_labels:
            raise ValueError("默认写法须属于场景写法选项")
        if self.default_tone not in self.tones:
            raise ValueError("默认语气须属于场景语气选项")
        recipe_ids = {
            recipe.id
            for pack in list_scenario_packs()
            if pack.id == self.id
            for recipe in pack.recipes
        }
        if set(self.recipe_styles) != recipe_ids:
            raise ValueError("配方写法推荐须完整覆盖且仅包含所属场景的配方")
        if any(style not in style_labels for style in self.recipe_styles.values()):
            raise ValueError("配方推荐写法须属于场景写法选项")
        return self


def _style(id_: str, label: str, description: str) -> ScenarioStyle:
    return ScenarioStyle(id=id_, label=label, description=description)


GONGWEN_PROFILE = ScenarioProfile(
    id="gongwen",
    name="公文与综合材料",
    description="规范表达、事实支撑和任务落实；党报写法仅在这一场景提供。",
    styles=(
        _style(
            "official-synthesis",
            "权威媒体综合写法",
            "以准确标题、平行小标题和分层论述组织材料；仅为结构方法提示。",
        ),
        _style(
            "people-commentary",
            "人民日报式消息评论",
            "先点明主题，再把已确认事实与观点连接，最后落到具体行动；不复制来源正文。",
        ),
        _style(
            "guangming-explanation",
            "光明日报式理性阐释",
            "由背景、概念和问题展开理性解释，区分事实与判断，保持平实克制。",
        ),
        _style(
            "qiushi-argument",
            "求是式理论论证",
            "先提出核心判断，再逐层展开依据、逻辑和实践路径；引文须另有真实出处。",
        ),
        _style(
            "official-evidence",
            "事实—问题—举措",
            "以已有材料交代现状，再分析问题与原因，最后提出相互对应的举措。",
        ),
        _style(
            "official-responsibility",
            "任务—责任—时限",
            "围绕执行事项组织内容，逐项核对责任主体、交付要求和时间节点。",
        ),
    ),
    tones=("严谨规范", "凝练有力", "务实亲切"),
    default_style="权威媒体综合写法",
    default_tone="严谨规范",
    recipe_styles={
        "work-summary": "事实—问题—举措",
        "briefing-material": "事实—问题—举措",
        "leadership-speech": "权威媒体综合写法",
        "research-report": "事实—问题—举措",
        "implementation-plan": "任务—责任—时限",
        "meeting-minutes": "任务—责任—时限",
    },
    source=ScenarioSource(
        title="公文写法参考与事实材料",
        description="党报文章用于结构、语气和句式参考；项目事实另从你提供的工作材料取证。选定写法不代表已检索文章。",
        action_label="选择党报写法参考",
        action="articles",
    ),
    labels=ScenarioLabels(
        topic="写作主题",
        purpose="写作目的",
        audience="阅读对象",
        materials="工作事实材料",
        requirements="行文要求",
        keywords="表达关键词",
        generate="生成材料初稿",
        review="检查规范与事实",
        reference_style="公文写法参考",
    ),
    placeholders=ScenarioLabels(
        topic="例如：某单位数字化转型阶段总结",
        purpose="例如：总结进展，分析不足，明确下一阶段任务",
        audience="例如：相关处室、项目参与单位",
        materials="粘贴已确认的工作记录、数据、时间节点及责任分工；与写法参考分开使用。",
        requirements="例如：所有数字有依据；问题与措施对应；写明责任与时限",
        keywords="例如：务实、协同、为民、落实",
        generate="先确认主题和事实，再生成符合文种的结构化初稿",
        review="核对行文关系、标题结构、事实依据与落实安排",
        reference_style="选择正式材料的结构和表达方法",
    ),
    checklist=(
        "文种与行文关系准确",
        "标题概括正文且层级平行",
        "数字、日期和名称均有材料依据",
        "问题与对策逐项对应",
        "任务包含责任与时限",
        "已完成人工复核",
    ),
    review_dimensions=("格式规范", "结构完整", "事实一致", "语言精炼"),
    example=ScenarioExample(
        topic="数字化转型阶段工作总结",
        purpose="总结阶段进展、分析问题并明确下一步安排",
        audience="项目参与处室及协作单位",
        materials="示例材料：统一事项平台已接入6个处室；组织培训2场。当前问题是字段标准不统一。下一步由项目组整理数据目录，完成日期待确认。以上数字仅供演示，正式使用前替换为真实记录。",
        requirements="区分已完成事项与下一步计划；时间未确认的地方明确标记待确认。",
        keywords="务实、协同、落实",
    ),
    prompt_guidance=(
        "按正式材料的行文关系和文种组织内容，避免没有事实支撑的套话与成果判断。",
        "人民日报、光明日报和求是等写法选项只是结构提示；未提供原始文章时不得声称已阅读或引用其正文。",
        "选用事实—问题—举措或任务—责任—时限等逻辑时，让每项判断和举措对应用户材料。",
    ),
)


WORKPLACE_PROFILE = ScenarioProfile(
    id="workplace",
    name="职场沟通",
    description="为协作、汇报和业务决策服务；先说清信息，再推动具体行动。",
    styles=(
        _style(
            "bottom-line-first", "结论先行", "首段直接给出结论、请求或状态，再补充必要背景和依据。"
        ),
        _style(
            "pyramid", "金字塔表达", "一个核心结论统领若干并列理由，每个理由再由事实或例子支撑。"
        ),
        _style(
            "scqa",
            "SCQA问题解决",
            "按情境、冲突、问题、答案展开；冲突来自真实业务材料，而非人为制造危机。",
        ),
        _style(
            "action-email",
            "行动邮件",
            "主题写明事项，正文说明结论与背景，收尾列出动作、负责人、期限和回复方式。",
        ),
        _style(
            "evidence-retrospective",
            "事实复盘",
            "对照目标与实际结果，分析差异及原因，形成可验证的经验和后续实验。",
        ),
        _style(
            "decision-comparison",
            "决策比较",
            "先统一评价标准，再比较选项的收益、成本、风险和依赖，明确推荐及不确定性。",
        ),
        _style(
            "status-risk-next",
            "进展—风险—下一步",
            "把工作记录转化为成果、状态、阻塞和下一节点，突出需要协助的事项。",
        ),
    ),
    tones=("清晰直接", "专业友好", "简洁务实", "有据可循"),
    default_style="结论先行",
    default_tone="清晰直接",
    recipe_styles={
        "work-email": "行动邮件",
        "weekly-report": "进展—风险—下一步",
        "business-proposal": "决策比较",
        "meeting-followup": "行动邮件",
        "presentation-outline": "金字塔表达",
    },
    source=ScenarioSource(
        title="业务材料与团队范例",
        description="优先使用需求说明、业务数据、会议记录、团队邮件和既有方案；方法卡为内置结构提示，不是已抓取的企业样文。",
        action_label="管理业务材料",
        action="materials",
    ),
    labels=ScenarioLabels(
        topic="沟通事项",
        purpose="期望结果",
        audience="收件人或决策者",
        materials="业务背景与事实",
        requirements="交付与协作要求",
        keywords="关键业务词",
        generate="生成工作初稿",
        review="检查清晰度与行动项",
        reference_style="职场表达方法",
    ),
    placeholders=ScenarioLabels(
        topic="例如：客户支持知识库改版方案",
        purpose="例如：请负责人确认试点范围，并协调产品和客服各一位对接人",
        audience="例如：业务负责人、产品经理与客服主管",
        materials="粘贴业务目标、当前数据、约束条件、会议记录或已有邮件；缺少负责人、期限或预算时明确标记。",
        requirements="例如：先给结论；比较两个方案；列明需决策事项与下次检查点",
        keywords="例如：客户体验、交付、协同、风险",
        generate="根据业务材料组织结论、依据与可执行的下一步",
        review="核对结论是否清晰、行动项是否完整、数据是否有据",
        reference_style="选择结论先行、金字塔、SCQA或其他业务表达方法",
    ),
    checklist=(
        "首段说明结论或沟通请求",
        "内容匹配收件人的决策需求",
        "事实、估算与意见明确区分",
        "选项比较采用一致标准",
        "行动项包含负责人和期限或待确认标记",
        "承诺与交付安排已由人工确认",
    ),
    review_dimensions=("结论清晰", "信息组织", "事实一致", "行动可执行"),
    example=ScenarioExample(
        topic="客户支持知识库改版方案",
        purpose="比较轻量整理与系统改版两条路径，供业务负责人确认试点范围",
        audience="业务负责人、产品经理与客服主管",
        materials="示例材料：客服反馈现有帮助文档存在重复条目和分类不一致。方案A先整理现有内容，方案B同时改版检索入口。目前尚未统计重复比例和实施成本；拟先由产品与客服共同盘点，负责人及完成日期待确认。",
        requirements="结论先行；在同一标准下比较方案；区分事实与待验证假设；不编造收益数字。",
        keywords="客户体验、知识库、协同、试点",
    ),
    prompt_guidance=(
        "使用专业、直接的职场语言，不把业务沟通改写成党政部署、政治表态或机关汇报。",
        "开头说明读者需要知道或决定什么，按背景、证据、选择和下一步组织必要信息。",
        "行动项、承诺、预算、期限和负责人仅来自材料；缺失信息标记待确认，不自行指派。",
        "方案比较与复盘应区分事实、估计和判断；不把预期价值写成已实现成果。",
    ),
)


MEDIA_PROFILE = ScenarioProfile(
    id="media",
    name="内容传播",
    description="围绕读者价值和可信信息，组织新闻、品牌内容与社交表达。",
    styles=(
        _style(
            "inverted-pyramid",
            "倒金字塔新闻",
            "先交代最重要的新闻事实，再按重要程度展开细节与背景。",
        ),
        _style(
            "reader-value",
            "读者价值式",
            "从读者实际问题切入，给出明确收获，用可信事实支撑内容价值。",
        ),
        _style(
            "narrative-scene",
            "场景叙事",
            "以真实场景、人物行动和变化组织故事；不存在的细节和引语保留待补。",
        ),
        _style(
            "explain-stepwise", "层递解释", "先解释是什么，再说明为什么与如何做，逐层降低理解门槛。"
        ),
        _style(
            "short-social",
            "社交短文",
            "聚焦单一信息，简洁开场，给出必要事实，以自然的互动提示收束。",
        ),
        _style(
            "spoken-beats",
            "口播节拍",
            "按开场、信息推进、关键转折与结尾安排短句，保留适当停顿和口语节奏。",
        ),
    ),
    tones=("清楚可信", "自然亲切", "生动克制", "简洁鲜明"),
    default_style="读者价值式",
    default_tone="清楚可信",
    recipe_styles={
        "press-release": "倒金字塔新闻",
        "wechat-article": "读者价值式",
        "social-post": "社交短文",
        "short-video-script": "口播节拍",
    },
    source=ScenarioSource(
        title="传播事实与品牌材料",
        description="从新闻通稿、采访记录、产品说明、品牌术语和已有内容取材；事实与创意分开，不默认套用党报风格。",
        action_label="管理传播材料",
        action="materials",
    ),
    labels=ScenarioLabels(
        topic="传播主题",
        purpose="读者收获与发布目标",
        audience="目标读者",
        materials="新闻事实与内容素材",
        requirements="渠道与品牌要求",
        keywords="核心信息词",
        generate="生成内容初稿",
        review="检查表达与事实",
        reference_style="内容表达方法",
    ),
    placeholders=ScenarioLabels(
        topic="例如：团队知识库新版试用邀请",
        purpose="例如：讲清本次更新解决的问题，并邀请同事试用反馈",
        audience="例如：首次使用产品的普通用户",
        materials="粘贴可公开的新闻事实、访谈记录、功能说明或品牌用语；人物引语、效果数字和发布信息须有来源。",
        requirements="例如：不用夸张承诺；正文500字内；清楚标出试用条件",
        keywords="例如：易用、协作、体验、反馈",
        generate="把可信素材组织成符合渠道和读者习惯的初稿",
        review="核对标题与正文一致、引语可追溯、效果描述有依据",
        reference_style="选择新闻、解释、叙事、社交或口播结构",
    ),
    checklist=(
        "标题与正文事实一致",
        "开场提供清晰阅读价值",
        "数字、引语与案例有来源",
        "事实与创意表达明确区分",
        "渠道篇幅与品牌要求匹配",
        "发布范围和行动提示已人工确认",
    ),
    review_dimensions=("读者价值", "叙事结构", "事实一致", "渠道适配"),
    example=ScenarioExample(
        topic="团队知识库新版试用邀请",
        purpose="说明本次更新的用途，并邀请同事参与体验反馈",
        audience="需要查找内部帮助文档的团队成员",
        materials="示例材料：新版知识库增加按问题分类的入口，合并了部分重复条目，目前处于内部试用阶段。尚无效率提升数据。试用入口、开放日期与反馈联系人待确认。",
        requirements="采用友好简洁的表达；不声称正式发布；不编造用户评价和效率提升比例。",
        keywords="知识库、试用、查找、反馈",
    ),
    prompt_guidance=(
        "先判断发布渠道、读者和单一核心信息，再选择新闻、解释、叙事或口播结构。",
        "不默认使用政治口号或机关部署用语；表达应服务读者理解与内容目标。",
        "标题可以提炼价值和设置真实问题，但不得增加未证实的效果、事件、人物经历或承诺。",
        "所有人物引语、新闻六要素、产品能力和数字回到材料；创意不能补造事实。",
    ),
)


ACADEMIC_PROFILE = ScenarioProfile(
    id="academic",
    name="学术与研究写作",
    description="围绕研究问题组织文献、方法与证据；明确研究边界和待核验内容。",
    styles=(
        _style(
            "thematic-review",
            "主题式文献综述",
            "按主题、方法与分歧综合已导入文献，比较证据后讨论研究空白，避免逐篇罗列。",
        ),
        _style(
            "imrad",
            "IMRaD研究结构",
            "按引言、方法、结果、讨论组织研究；结果只使用用户真实数据，缺失时保留待补。",
        ),
        _style(
            "claim-evidence",
            "论点—证据—推理",
            "逐项给出主张、可追溯证据及推理过程，区分证据直接支持与作者解释。",
        ),
        _style(
            "structured-abstract",
            "结构化摘要",
            "由目的、方法、结果与结论压缩研究全文；不把研究计划改写成已完成发现。",
        ),
        _style(
            "reviewer-response",
            "逐条审稿回复",
            "逐条对应审稿意见，说明回应依据、实际修改及稿件位置，保留尚未完成的修改标记。",
        ),
        _style(
            "calibrated-expression",
            "审慎学术表达",
            "以证据强度校准措辞，说明样本和方法限制，避免把相关关系表述为因果结论。",
        ),
        _style(
            "question-method",
            "问题—概念—方法",
            "由研究问题界定概念和分析框架，再说明资料条件、方法与可回答范围。",
        ),
    ),
    tones=("客观审慎", "逻辑严密", "清晰克制", "专业简明"),
    default_style="主题式文献综述",
    default_tone="客观审慎",
    recipe_styles={
        "literature-review": "主题式文献综述",
        "research-outline": "问题—概念—方法",
        "research-abstract": "结构化摘要",
        "reviewer-response": "逐条审稿回复",
    },
    source=ScenarioSource(
        title="研究文献与证据材料",
        description="使用你导入的论文、书目、研究笔记与数据说明。写法卡不是学术文献；只有显式发起文献查询才会查询外部书目信息，书目命中不代表读过全文。",
        action_label="打开学术文献与证据",
        action="academic",
    ),
    labels=ScenarioLabels(
        topic="研究主题或问题",
        purpose="研究目标",
        audience="学科读者或目标期刊",
        materials="文献、数据与研究笔记",
        requirements="研究边界与引用要求",
        keywords="研究关键词",
        generate="生成研究初稿",
        review="检查论证与引用",
        reference_style="学术组织与表达方法",
    ),
    placeholders=ScenarioLabels(
        topic="例如：数字化协作工具与团队知识共享的关系",
        purpose="例如：梳理已有研究的主题、方法和分歧，界定可研究的问题",
        audience="例如：组织管理领域研究者；目标期刊要求另行提供",
        materials="导入真实文献或粘贴带出处和页码的摘录、研究笔记、方法说明与数据。仅有题目时先形成研究框架，不生成假引用或研究结果。",
        requirements="例如：按主题综合文献；区分相关与因果；未核验引用标记待补；遵循指定引用体例",
        keywords="例如：数字化协作、知识共享、组织学习",
        generate="以已有证据组织研究框架、论证与待补信息",
        review="核对主张与证据的对应、方法边界、引用位置及书目信息",
        reference_style="选择综述、IMRaD、论证、摘要、回复或审慎表达方法",
    ),
    checklist=(
        "研究问题与概念边界明确",
        "文献主张对应真实来源及定位",
        "方法与结果来自实际研究材料",
        "相关、因果与推测表述相区分",
        "引用位置、书目信息及格式已核对",
        "研究局限与学术贡献经人工审阅",
    ),
    review_dimensions=("问题与论证", "结构与方法", "证据与引用", "学术表达"),
    example=ScenarioExample(
        topic="数字化协作工具与团队知识共享的关系",
        purpose="构建主题式文献综述框架，明确概念、研究分歧和后续检索问题",
        audience="组织管理与信息系统领域研究者",
        materials="示例任务：关注工具使用、沟通方式和知识共享之间的关系。当前尚未导入文献、原始数据或研究结果。请先列出概念界定、主题分组和证据比较框架；作者、年份、DOI、研究结论与引用位置均待真实文献补齐。",
        requirements="不虚构文献、DOI或数据；没有证据时保留待补标记；明确区分研究问题、假设和已有发现。",
        keywords="数字化协作、知识共享、组织学习",
    ),
    prompt_guidance=(
        "使用学术研究语体，以研究问题、概念、方法、证据和限定性结论组织内容，不套用公文动员或工作部署语言。",
        "文献综述应围绕主题和方法比较真实导入文献，区分作者原始发现、综述归纳和待验证解释。",
        "不得编造作者、年份、文献题目、DOI、页码、引用、实验、样本、统计结果或审稿修改完成状态。",
        "未获得全文时不得声称已经阅读全文；书目元数据和摘要不等于完整研究证据。",
        "没有文献或数据时只提供研究框架、检索问题和待补位置；不把拟开展研究表述为已完成研究。",
        "根据证据强度采用审慎措辞，显式说明研究局限，避免无依据的因果和创新性判断。",
    ),
)


_PROFILES: tuple[ScenarioProfile, ...] = (
    GONGWEN_PROFILE,
    WORKPLACE_PROFILE,
    MEDIA_PROFILE,
    ACADEMIC_PROFILE,
)

_DOCUMENT_TYPE_ALIASES: dict[str, ScenarioPackId] = {
    "通知": "gongwen",
    "请示": "gongwen",
    "报告": "gongwen",
    "函": "gongwen",
    "公文": "gongwen",
    "公函": "gongwen",
    "讲话": "gongwen",
    "领导讲话": "gongwen",
    "工作邮件": "workplace",
    "职场邮件": "workplace",
    "商业方案": "workplace",
    "商业计划书": "workplace",
    "项目复盘": "workplace",
    "会议跟办清单": "workplace",
    "职场沟通": "workplace",
    "通用长文": "workplace",
    "自定义": "workplace",
    "公众号": "media",
    "社交文案": "media",
    "口播稿": "media",
    "品牌文案": "media",
    "学术论文": "academic",
    "论文": "academic",
    "论文摘要": "academic",
    "研究论文": "academic",
    "期刊论文": "academic",
    "学术摘要": "academic",
    "研究摘要": "academic",
    "开题报告": "academic",
    "审稿意见回复": "academic",
    "email": "workplace",
    "proposal": "workplace",
    "weekly report": "workplace",
    "press release": "media",
    "social post": "media",
    "academic paper": "academic",
    "literature review": "academic",
    "abstract": "academic",
}


def get_scenario_profile(pack_id: str) -> ScenarioProfile:
    """Resolve the immutable UI and prompt profile by an explicit scenario id."""

    for profile in _PROFILES:
        if profile.id == pack_id:
            return profile
    raise ValueError(f"未知场景包：{pack_id}")


def scenario_for_document_type(document_type: str) -> ScenarioProfile:
    """Resolve known types; custom and empty types use neutral workplace writing."""

    normalized = document_type.strip().casefold()
    for pack in list_scenario_packs():
        if any(
            normalized in {recipe.content_type.casefold(), recipe.name.casefold()}
            for recipe in pack.recipes
        ):
            return get_scenario_profile(pack.id)
    return get_scenario_profile(_DOCUMENT_TYPE_ALIASES.get(normalized, "workplace"))


def scenario_catalog() -> dict[str, JsonValue]:
    """Return a fresh JSON catalog, deriving all recipes from the core registry."""

    profiles: dict[str, JsonValue] = {
        profile.id: profile.model_dump(mode="json") for profile in _PROFILES
    }
    recipes: dict[str, JsonValue] = {
        pack.id: [recipe.model_dump(mode="json") for recipe in pack.recipes]
        for pack in list_scenario_packs()
    }
    return {"schema_version": 1, "profiles": profiles, "recipes": recipes}


__all__ = [
    "ACADEMIC_PROFILE",
    "GONGWEN_PROFILE",
    "MEDIA_PROFILE",
    "WORKPLACE_PROFILE",
    "ScenarioExample",
    "ScenarioLabels",
    "ScenarioProfile",
    "ScenarioSource",
    "ScenarioStyle",
    "get_scenario_profile",
    "scenario_catalog",
    "scenario_for_document_type",
]
