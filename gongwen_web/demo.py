"""Deterministic writing, rewriting, and review engines for the local demo."""

# Chinese punctuation is intentional in generated official-document copy.
# ruff: noqa: RUF001

from __future__ import annotations

import re

from gongwen_web.methodologies import normalize_document_type, resolve_content_methodology
from gongwen_web.models import (
    GeneratedDocument,
    GenerateRequest,
    GenerationMeta,
    OutlineItem,
    ReviewIssue,
    ReviewMetrics,
    ReviewRequest,
    ReviewResult,
    RewriteRequest,
    RewriteResult,
    SourceCard,
    TitleCandidate,
)
from gongwen_web.title_engine import (
    as_document_title_candidates,
    clean_topic,
    generate_titles_demo,
    score_title,
    title_request_from_generate,
)
from yanzhang_core.packs import list_recipes
from yanzhang_core.scenario_profiles import scenario_for_document_type

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；])|[\r\n]+")
_HEADING = re.compile(r"^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[.、])")
_PLACEHOLDER = re.compile(
    r"(?:\{\{[^{}]+\}\}|\[[A-Z][A-Z0-9_]*\]|"
    r"【[^】]*(?:待补|日期|单位|姓名|金额|时间|地点|部门|事项)[^】]*】)"
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_SEMANTIC_HEADING_PREFIX = re.compile(
    r"^(?:(?:[一二三四五六七八九十]+|\d+)[.、]|[（(](?:[一二三四五六七八九十]+|\d+)[）)])\s*"
)


_OFFICIAL_DOCUMENT_TYPES = (
    "通知",
    "请示",
    "报告",
    "函",
    "会议纪要",
    "工作总结",
    "实施方案",
    "讲话稿",
    "汇报材料",
)


def supported_document_types() -> tuple[str, ...]:
    """Return document types in their intended UI order."""

    return tuple(
        dict.fromkeys(
            (*_OFFICIAL_DOCUMENT_TYPES, *(recipe.content_type for recipe in list_recipes()))
        )
    )


def generate_demo(request: GenerateRequest) -> GeneratedDocument:
    """Build a complete, repeatable Chinese official-document draft."""

    document_type = normalize_document_type(request.document_type)
    profile = scenario_for_document_type(document_type)
    topic = clean_topic(request.topic)
    methodology = resolve_content_methodology(
        document_type,
        request.content_methodology_id,
        custom=request.custom_methodology,
    )
    title_result = generate_titles_demo(title_request_from_generate(request))
    title_candidates = as_document_title_candidates(title_result)
    title, title_candidates = _apply_selected_title(
        request.selected_title,
        title_candidates,
        topic=topic,
        document_type=document_type,
        materials=request.material_text(),
    )
    facts = _material_facts(request.material_text())
    cards = [
        SourceCard(id=f"material-{index}", label=f"用户材料 {index}", excerpt=fact)
        for index, fact in enumerate(facts, start=1)
    ]
    cards.append(
        SourceCard(
            id="writing-style",
            label=resolved_style(document_type, request.reference_style)[0],
            excerpt=resolved_style(document_type, request.reference_style)[1],
            source_type="写法参考（仅结构与句式特征）",
        )
    )
    cards.append(
        SourceCard(
            id=f"methodology-{methodology.id}",
            label=f"内容方法论｜{methodology.name}",
            excerpt=f"{methodology.logic}；{methodology.fact_strategy}",
            source_type=(
                "用户自定义内容方法论" if methodology.source == "custom" else "预置内容方法论"
            ),
        )
    )
    cards.extend(
        SourceCard(
            id=reference.id or f"style-reference-{index}",
            label=f"{reference.source_name}｜{reference.title}".strip("｜"),
            excerpt=(reference.excerpt or "；".join(reference.style_features))[:500],
            source_type="文章来源（仅写法参考）",
            url=reference.url,
            published_at=reference.published_at,
        )
        for index, reference in enumerate(request.style_references, start=1)
        if profile.id == "gongwen" or not _official_reference(reference.source_name)
    )
    outline = [
        OutlineItem(
            heading=heading,
            content=_section_text(
                document_type=document_type,
                heading=heading,
                topic=topic,
                purpose=request.purpose,
                facts=facts,
                section_index=index,
                length=request.length,
                requirements=request.requirements,
                tone=request.tone,
                fact_lock=request.fact_lock,
                reference_style=request.reference_style,
            ),
        )
        for index, heading in enumerate(methodology.headings)
    ]
    if profile.id != "gongwen":
        outline = _scenario_outline(
            request, methodology.headings, methodology.section_purposes, facts
        )
    blocks: list[str] = []
    if request.audience and document_type in {"通知", "请示", "报告", "函", "邮件"}:
        blocks.append(f"{request.audience}：")
    for item in outline:
        blocks.extend((item.heading, item.content))
    closing = _closing(document_type, request.requirements)
    if closing:
        blocks.append(closing)
    content = "\n\n".join(blocks)
    placeholders = sorted(set(_PLACEHOLDER.findall(f"{title}\n{content}")))
    return GeneratedDocument(
        title=title,
        title_candidates=title_candidates,
        outline=outline,
        content=content,
        facts=facts,
        source_cards=cards,
        placeholders=placeholders,
        content_methodology=methodology,
        meta=GenerationMeta(mode="demo"),
    )


def _apply_selected_title(
    selected_title: str | None,
    candidates: list[TitleCandidate],
    *,
    topic: str,
    document_type: str,
    materials: str,
) -> tuple[str, list[TitleCandidate]]:
    """Promote an explicitly selected title before drafting the body."""

    chosen = selected_title.strip() if selected_title else ""
    if not chosen:
        return candidates[0].title, candidates
    for candidate in candidates:
        if candidate.title == chosen:
            ordered = [candidate, *(item for item in candidates if item is not candidate)]
            return chosen, [
                item.model_copy(update={"selected": index == 0, "rank": index + 1})
                for index, item in enumerate(ordered)
            ]
    dimensions = score_title(
        chosen,
        topic=topic,
        document_type=document_type,
        materials=materials,
        formula_fit=100,
    )
    manual = TitleCandidate(
        title=chosen,
        style="用户选定",
        reason="先确定标题，再按所选内容方法论组织正文。",
        selected=True,
        formula_id="selected",
        formula_name="用户选定标题",
        score=round(sum(dimensions.model_dump().values()) / len(dimensions.model_dump())),
        score_dimensions=dimensions.model_dump(),
        rank=1,
    )
    return chosen, [
        manual,
        *[
            item.model_copy(update={"selected": False, "rank": index + 2})
            for index, item in enumerate(candidates[:-1])
        ],
    ]


def rewrite_demo(request: RewriteRequest) -> RewriteResult:
    """Apply a deterministic editorial pass without a network model."""

    if request.document_type and scenario_for_document_type(request.document_type).id != "gongwen":
        return _rewrite_scenario(request)
    text = _normalize_spacing(request.text)
    changes: list[str] = []
    mode = request.mode.casefold()
    instruction = request.instruction
    if mode in {"concise", "shorten", "精简", "压缩"} or "精简" in instruction:
        text = _make_concise(text)
        changes.append("压缩重复和铺垫性表达")
    elif mode in {"expand", "扩写", "充实"} or "扩写" in instruction:
        text = _expand(text)
        changes.append("补充目标、抓手和落实要求")
    else:
        text = _make_formal(text)
        changes.extend(("调整口语化表达", "强化句间衔接", "统一公文语气"))
    if request.tone in {"部署有力", "行动导向"}:
        text = text.replace("要做好", "要压紧压实责任，扎实做好")
        changes.append("增强部署语气")
    return RewriteResult(text=text, changes=_dedupe(changes), meta=GenerationMeta(mode="demo"))


def review_demo(request: ReviewRequest) -> ReviewResult:
    """Inspect structure, placeholders, sentence length, and vague wording."""

    content = request.content.strip()
    paragraphs = [line.strip() for line in content.splitlines() if line.strip()]
    document_type = normalize_document_type(request.document_type)
    scene = scenario_for_document_type(document_type).id
    legacy = not request.document_type or scene == "gongwen"
    known_headings = {
        section.title
        for recipe in list_recipes()
        if recipe.content_type == document_type
        for section in recipe.sections
    }
    headings = [
        line for line in paragraphs if _HEADING.match(line) or line.lstrip("# ") in known_headings
    ]
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(content) if part.strip()]
    long_sentences = [part for part in sentences if len(part) > 90]
    vague_terms = ("有关", "相关", "适时", "尽快", "若干", "进一步")
    vague_count = sum(content.count(term) for term in vague_terms)
    placeholders = _PLACEHOLDER.findall(content)
    material_numbers = set(_NUMBER.findall(request.materials))
    content_numbers = set(_NUMBER.findall(content))
    unverified_numbers = sorted(content_numbers - material_numbers) if request.materials else []
    issues: list[ReviewIssue] = []
    if not request.title.strip():
        issues.append(
            ReviewIssue(
                level="warning",
                category="标题",
                message="尚未填写文件标题。",
                suggestion="补充由事由和文种构成的完整标题。"
                if legacy
                else "补充能准确识别主题和沟通目的的标题。",
            )
        )
    if legacy and len(content) < 180:
        issues.append(
            ReviewIssue(
                level="suggestion",
                category="完整性",
                message="正文篇幅较短，论述可能不够充分。",
                suggestion="核对背景、任务、责任和时限是否齐全。",
            )
        )
    if legacy and not headings:
        issues.append(
            ReviewIssue(
                level="warning",
                category="结构",
                message="未识别到规范的层级标题。",
                suggestion="使用“一、……”“二、……”组织主要内容。",
            )
        )
    if long_sentences:
        issues.append(
            ReviewIssue(
                level="suggestion",
                category="表达",
                message=f"发现 {len(long_sentences)} 个超过90字的长句。",
                suggestion="拆分复句，分别表达依据、举措和要求。",
            )
        )
    if vague_count:
        issues.append(
            ReviewIssue(
                level="suggestion",
                category="准确性",
                message=f"发现 {vague_count} 处可能需要明确的概括性表述。",
                suggestion=(
                    "明确概念、限定范围并补充证据定位，避免把推测写成结论。"
                    if scene == "academic"
                    else "结合任务需要明确对象、条件、时间或判断依据。"
                ),
            )
        )
    if placeholders:
        issues.append(
            ReviewIssue(
                level="error",
                category="待补信息",
                message=f"正文仍有 {len(placeholders)} 个模板变量或待补项。",
                suggestion="导出正式文件前逐项替换并复核。",
            )
        )
    if unverified_numbers:
        preview = "、".join(unverified_numbers[:5])
        issues.append(
            ReviewIssue(
                level="warning",
                category="事实依据",
                message=f"正文中的数字 {preview} 未在参考材料中检出。",
                suggestion="核对数字来源；如属标题序号或通用表述，可人工确认后保留。",
            )
        )
    if scene == "academic" and request.document_type:
        issues.extend(_academic_review_issues(request))
    score = max(
        0,
        100
        - sum(
            16 if item.level == "error" else 8 if item.level == "warning" else 4 for item in issues
        ),
    )
    summary = (
        "结构和表达整体规范，可进入人工复核。"
        if score >= 88
        else "初稿框架已经形成，建议按问题清单完成一轮修改。"
    )
    return ReviewResult(
        score=score,
        summary=summary,
        issues=issues,
        metrics=ReviewMetrics(
            character_count=len(content),
            paragraph_count=len(paragraphs),
            heading_count=len(headings),
            long_sentence_count=len(long_sentences),
            vague_expression_count=vague_count,
            placeholder_count=len(placeholders),
        ),
        meta=GenerationMeta(mode="demo"),
    )


def resolved_style(document_type: str, requested: str) -> tuple[str, str]:
    """Resolve style id/label inside the current scenario, never via a party-media default."""

    profile = scenario_for_document_type(document_type)
    style = next((item for item in profile.styles if requested in {item.id, item.label}), None)
    if style is None:
        recipe = next(
            (
                item
                for item in list_recipes(profile.id)
                if item.content_type == normalize_document_type(document_type)
            ),
            None,
        )
        default = (
            profile.recipe_styles.get(recipe.id, profile.default_style)
            if recipe
            else profile.default_style
        )
        style = next(item for item in profile.styles if item.label == default)
    return style.label, style.description


def _official_reference(source: str) -> bool:
    return any(name in source for name in ("人民日报", "人民网", "光明日报", "光明网", "求是"))


_SECTION_HINTS: dict[str, tuple[str, str]] = {
    "背景与结论": (
        "这次沟通围绕“{topic}”，希望先明确共同需要处理的事项。",
        "一句话说明沟通目的、当前结论和需要对方做什么",
    ),
    "必要信息": ("以下信息供沟通和判断时参考。", "与本次沟通直接相关的背景、附件或事实"),
    "下一步": (
        "后续动作需要逐项确认，避免把建议当作已经作出的承诺。",
        "请求事项、负责人、反馈方式和已确认的时间",
    ),
    "本周完成": (
        "本周成果以实际交付和确认记录为准。",
        "已完成事项、交付物及对应记录；未完成事项移入进行中",
    ),
    "进行中": (
        "进行中的事项需要说明当前状态和下一个可检查的节点。",
        "当前进度、剩余工作和下一节点",
    ),
    "风险与协同": (
        "需要协作的事项应说明阻塞、影响和所需支持。",
        "实际风险、依赖事项和需要的支持；未确认风险须明确标识",
    ),
    "下周计划": (
        "下周计划应区分优先事项与可选事项，并关联具体交付物。",
        "下周优先级、交付物、负责人和确认后的时间安排",
    ),
    "问题与机会": (
        "本方案围绕“{topic}”，先界定业务问题及其影响范围。",
        "业务现状、具体痛点及支持判断的材料",
    ),
    "目标与原则": (
        "成功标准需要与问题对应，并明确衡量方式和约束条件。",
        "目标、验收口径、资源与边界条件",
    ),
    "方案设计": (
        "方案设计需要交代动作、依赖和取舍，使决策者能比较不同路径。",
        "可选路径、资源投入、协作方式及选择依据",
    ),
    "预期价值": (
        "预期价值属于待验证判断，应与已经实现的结果分开表达。",
        "收益假设、测算口径与证据；没有数据时保持定性描述",
    ),
    "风险与推进": (
        "实施节奏需要与可用资源相匹配，并保留调整和退出条件。",
        "阶段交付、主要风险、应对方式和推进条件",
    ),
    "问题与范围": (
        "本综述围绕“{topic}”组织研究问题、概念与文献范围。",
        "研究问题、核心概念、检索库、检索式、时间范围及纳入排除标准",
    ),
    "主题脉络": (
        "主题综述应围绕共同问题组织证据，而非按作者逐篇罗列。",
        "主题分类；每类的来源、研究对象、方法、主要结论与页码定位",
    ),
    "证据与分歧": (
        "比较研究结论之前，需要先核对研究对象、测量口径和方法是否可比。",
        "支持与相反证据、方法差异、样本边界及引用定位",
    ),
    "研究空白": (
        "研究空白应由已纳入文献的覆盖范围和证据局限推导，不预设“尚无研究”。",
        "被文献证据支持的未回答问题、依据及下一步研究方向",
    ),
    "研究问题": (
        "围绕“{topic}”，先将宽泛主题收束为可回答的研究问题。",
        "研究对象、具体问题、问题意义和可回答性",
    ),
    "分析框架": (
        "分析框架需要区分概念定义、理论假设与待检验关系。",
        "核心概念、变量或分析维度及其来源",
    ),
    "资料与方法": (
        "研究设计应与实际资料条件一致；计划采用的方法不代表已经完成研究。",
        "可用数据、取样范围、分析方法及适用条件",
    ),
    "章节结构": (
        "建议按问题提出、概念与文献、资料与方法、分析、讨论与结论组织章节。",
        "每章对应的研究问题、所需材料及预期分析任务",
    ),
    "背景与目的": (
        "本摘要对应“{topic}”研究，背景和目的应从原文提炼。",
        "原文明确提出的问题与研究目的",
    ),
    "方法": ("方法描述应与原文实际实施的设计保持一致。", "实际样本、数据来源、研究设计及分析方法"),
    "结果": (
        "此处仅呈现原文中已经得到的研究发现，不把研究计划写成结果。",
        "原文中的实际研究结果、关键数值与不确定性",
    ),
    "结论": (
        "结论需要与实际结果对应，同时保留研究限制和适用边界。",
        "原文结论、局限及适用范围；结果未提供时暂留空",
    ),
    "总体说明": (
        "感谢审稿人对稿件的审阅。以下按意见逐条整理回应与修改依据。",
        "审稿轮次、意见总览及实际修订概况",
    ),
    "逐条回复": (
        "审稿意见：【待补：原意见】\n回应草稿：【待补：回应、证据与是否采纳；尚未修改时写明计划】",
        "逐条对应的审稿原意见和回应依据",
    ),
    "修改定位": (
        "修改定位应以当前稿件实际内容为准，避免笼统声称已经完成修改。",
        "实际修改内容、章节、页码及行号；未实施的修改标明待处理",
    ),
    "保留意见": (
        "对未采纳的建议，应解释研究边界和证据理由，保持尊重且可核查。",
        "未采纳意见、理由及支持材料；如无此项可删除",
    ),
    "导语": (
        "“{topic}”的核心信息应在开头交代，优先使用已经确认的新闻事实。",
        "何人、何事、何时、何地及消息来源",
    ),
    "主体": (
        "主体按信息重要程度补充事实；直接引语应保留真实出处。",
        "事件过程、必要细节、已核实引语及来源",
    ),
    "背景": (
        "背景只补充理解本次事件所必需的上下文，并区分历史事实与当前情况。",
        "背景材料及时间范围",
    ),
    "开场": (
        "关于“{topic}”，先分享一条与读者直接相关的信息。",
        "最重要的真实信息或可确认的个人观点",
    ),
    "正文": ("这条内容聚焦“{topic}”，用简短文字讲清一个重点。", "核心信息、真实案例或已核实依据"),
    "收束": (
        "如果你也关注“{topic}”，欢迎分享你的看法。",
        "可选的了解入口或行动提示；未提供链接时不编造",
    ),
    "会议结论": ("会议结论应区分已确认决定与尚在讨论的建议。", "原记录中已确认的结论及对应议题"),
    "行动项": (
        "按动作、负责人、期限、当前状态建立可跟踪的行动清单。",
        "行动项｜负责人｜期限｜状态｜原始记录定位",
    ),
    "依赖与风险": (
        "行动项之间的依赖和阻塞需要向相关协作者明确。",
        "依赖事项、阻塞影响、需要的支持与确认人",
    ),
    "待确认事项": (
        "暂未确定的信息保留为问题，不替与会者作出决定。",
        "待确认问题、确认对象和反馈方式",
    ),
    "核心结论": (
        "本次演示围绕“{topic}”，希望听众先理解一个核心判断。",
        "一句话结论及其最重要的证据",
    ),
    "叙事主线": (
        "建议按问题、证据、选项与行动组织演示，保持每一步的逻辑联系。",
        "各部分的过渡关系与对应材料",
    ),
    "逐页提纲": (
        "每页只承载一个主要判断，结论式标题下保留必要证据。",
        "页标题｜一句话结论｜要点｜图表或资料来源；按实际内容增删页面",
    ),
    "收束与行动": (
        "演示结束时回到最初的问题，明确希望听众确认的决定或行动。",
        "决策请求、后续动作及已确认的安排",
    ),
    "问题场景": (
        "从读者会遇到的具体问题进入“{topic}”，避免只给抽象结论。",
        "真实场景、读者困惑与材料依据；虚构示例须明确标识",
    ),
    "核心内容": (
        "围绕“{topic}”逐项讲清关键信息，区分事实、观点和建议。",
        "核心要点、对应证据与适用条件",
    ),
    "总结与行动": (
        "收束时回扣本文回答的问题，再给出与内容相符的下一步。",
        "可确认的总结与自然的行动建议",
    ),
    "开场钩子": (
        "用与观众直接相关的问题引入“{topic}”，不以夸张效果吸引注意。",
        "开场问题或真实现象及画面提示",
    ),
    "内容节拍": (
        "口播按一个信息点一个节拍展开，文字与画面相互补充。",
        "节拍｜口播要点｜画面提示｜事实来源；时长按实际试读确认",
    ),
    "关键转折": (
        "在关键位置说明信息之间的关系或常见误解，不虚构反转案例。",
        "有证据支持的关键认识与衔接句",
    ),
    "行动提示": (
        "最后给出一项自然且具体的了解或交流方式。",
        "与发布目的相符的行动提示；入口信息核对后填写",
    ),
    "背景与目标": (
        "本稿围绕“{topic}”，先说明需要回应的问题和写作边界。",
        "写作背景、具体目标与受众需要",
    ),
    "依据与边界": ("判断应与证据对应，并说明材料未覆盖的部分。", "真实材料、判断依据及信息缺口"),
    "结论与后续": (
        "最后归纳已获支持的要点，区分结论与待确认事项。",
        "有依据的结论及后续需要处理的问题",
    ),
}

_FACT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "本周完成": ("完成", "交付", "上线", "已确认"),
    "进行中": ("进行", "进度", "正在"),
    "风险与协同": ("风险", "阻塞", "依赖", "问题", "支持"),
    "下周计划": ("下周", "计划", "下一步"),
    "下一步": ("请", "计划", "确认", "截止", "下一步"),
    "问题与机会": ("问题", "痛点", "现状"),
    "目标与原则": ("目标", "原则", "约束"),
    "方案设计": ("方案", "路径", "资源"),
    "预期价值": ("收益", "预计", "成本"),
    "风险与推进": ("风险", "阶段", "实施", "试点"),
    "主题脉络": ("文献", "研究", "作者", "观点"),
    "证据与分歧": ("分歧", "差异", "相反", "对比", "结论"),
    "研究空白": ("空白", "不足", "局限"),
    "资料与方法": ("样本", "访谈", "问卷", "方法", "数据"),
    "方法": ("样本", "访谈", "问卷", "方法", "数据", "回归"),
    "结果": ("发现", "结果", "显著", "表明"),
    "结论": ("结论", "局限", "限制"),
    "逐条回复": ("审稿", "意见", "建议"),
    "修改定位": ("修改", "修订", "页码", "行号"),
}


def _semantic_heading(heading: str) -> str:
    """Match semantic slots without changing the user's display heading."""

    label = heading.strip().lstrip("# ")
    prefix = _SEMANTIC_HEADING_PREFIX
    while True:
        stripped = prefix.sub("", label, count=1).strip()
        if stripped == label:
            return label
        label = stripped


def _scenario_outline(
    request: GenerateRequest,
    headings: tuple[str, ...],
    purposes: tuple[str, ...],
    facts: list[str],
) -> list[OutlineItem]:
    """Produce editable scene-specific scaffolds, with every supplied fact traceable once."""

    profile = scenario_for_document_type(request.document_type)
    semantic_headings = tuple(_semantic_heading(heading) for heading in headings)
    title_slots = {"邮件主题", "标题", "标题与开场"}
    first_body = next(
        (index for index, slot in enumerate(semantic_headings) if slot not in title_slots), 0
    )
    buckets: list[list[tuple[int, str]]] = [[] for _ in headings]
    default_index = next(
        (
            index
            for index, slot in enumerate(semantic_headings)
            if slot in {"必要信息", "主题脉络", "主体", "正文", "核心内容"}
        ),
        first_body,
    )
    for fact_index, fact in enumerate(facts, 1):
        matches = [
            (sum(word in fact for word in _FACT_KEYWORDS.get(slot, ())), index)
            for index, slot in enumerate(semantic_headings)
        ]
        hits, index = max(matches, key=lambda value: (value[0], value[1]))
        buckets[index if hits else default_index].append((fact_index, fact))
    result: list[OutlineItem] = []
    for index, (heading, purpose) in enumerate(zip(headings, purposes, strict=True)):
        slot = semantic_headings[index]
        if slot in title_slots:
            parts = [request.topic, "【待补：按受众和沟通目的确认开头重点】"]
        else:
            lead, missing = _SECTION_HINTS.get(
                slot,
                (
                    f"按自定义结构，本节需要说明：{purpose.rstrip('。')}。",
                    "与该部分直接相关的事实、论点及证据定位",
                ),
            )
            parts = [lead.replace("{topic}", request.topic)]
            if index == first_body and request.purpose:
                parts.append(f"本稿目标：{request.purpose.rstrip('。')}。")
            if not buckets[index]:
                parts.append(f"【待补：{missing}】")
        if buckets[index]:
            parts.extend(f"{fact}（用户材料 {number}）" for number, fact in buckets[index])
            if profile.id == "academic":
                parts.append("【待补：上述材料对应的真实文献、页码或段落定位，并据此完成比较分析】")
        result.append(OutlineItem(heading=heading, content="\n".join(parts)))
    return result


def _rewrite_scenario(request: RewriteRequest) -> RewriteResult:
    profile = scenario_for_document_type(request.document_type)
    text = _normalize_spacing(request.text)
    changes = ["保留原有事实、称谓和引用，整理空白与段落"]
    if (
        request.mode.casefold() in {"concise", "shorten", "精简", "压缩"}
        or "精简" in request.instruction
    ):
        for phrase in ("需要指出的是，", "众所周知，", "从某种意义上说，", "可以说，", "应该说，"):
            text = text.replace(phrase, "")
        changes.append("删除铺垫性套语，不替换为公文措辞")
    elif request.mode.casefold() in {"expand", "扩写", "充实"} or "扩写" in request.instruction:
        hint = (
            "主张的证据、引用定位及适用边界"
            if profile.id == "academic"
            else "需要补充的背景、依据或后续动作"
        )
        text += f"\n\n【待补：{hint}】"
        changes.append("标出扩写所需信息，不新增事实")
    else:
        changes.append(f"按{profile.name}保留原文语域；模板模式仅做基础整理")
    return RewriteResult(text=text, changes=changes, meta=GenerationMeta(mode="demo"))


def _academic_review_issues(request: ReviewRequest) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    if not request.materials.strip():
        issues.append(
            ReviewIssue(
                level="warning",
                category="证据边界",
                message="尚未提供用于核对研究主张的原文或文献材料。",
                suggestion="关联真实来源与页码或段落定位；当前规则检查不代表学术事实已获证实。",
            )
        )
    if any(term in request.content for term in ("首次证明", "填补空白", "国内首创", "彻底解决")):
        issues.append(
            ReviewIssue(
                level="warning",
                category="结论边界",
                message="发现需要充分文献证据支持的绝对化创新或结论表述。",
                suggestion="回查文献覆盖范围及证据，改为与研究结果和适用条件相符的限定表达。",
            )
        )
    return issues


def _material_facts(material: str) -> list[str]:
    if not material:
        return []
    facts: list[str] = []
    for part in _SENTENCE_SPLIT.split(material):
        cleaned = re.sub(r"^(?:[•·\-—]\s*|\d+[.、]\s+)", "", part.strip())
        if len(cleaned) < 4:
            continue
        if cleaned[-1] not in "。！？；":
            cleaned += "。"
        facts.append(cleaned)
        if len(facts) == 40:
            break
    return _dedupe(facts)


def _section_text(
    *,
    document_type: str,
    heading: str,
    topic: str,
    purpose: str,
    facts: list[str],
    section_index: int,
    length: str,
    requirements: str,
    tone: str,
    fact_lock: bool,
    reference_style: str,
) -> str:
    fact = _select_fact(facts, heading, section_index)
    if section_index == 0:
        lead = (
            f"坚持以实际需求为牵引，紧扣{topic}，统筹谋划、系统推进，"
            "推动各项工作有序衔接、落细落实。"
        )
        if purpose:
            lead = f"为{purpose.rstrip('。')}，{lead}"
    elif "问题" in heading or "不足" in heading or "短板" in heading:
        lead = (
            "坚持问题导向，对材料反映的事项逐项建立清单，明确改进措施和完成时限。"
            if fact or fact_lock
            else f"对照{topic}目标要求，系统梳理短板问题，逐项研究改进。"
        )
    elif "下一步" in heading or "安排" in heading or "要求" in heading or "保障" in heading:
        lead = (
            "健全任务清单、责任清单和时限清单，强化协同联动、过程调度和跟踪问效，"
            f"确保{topic}各项部署闭环落实、取得实效。"
        )
    elif document_type == "请示" and "请示事项" in heading:
        lead = f"现就{topic}有关事项提请审议，请予批复。"
    else:
        lead = (
            f"围绕{topic}重点任务，细化工作举措，明确责任分工，"
            "通过项目化推进、节点化管理，不断提升工作规范化、精细化水平。"
        )
    parts = [fact, lead] if fact else [lead]
    focus = _requirement_focus(requirements)
    if focus and any(word in heading for word in ("下一步", "安排", "举措", "步骤")):
        parts.append(focus)
    if tone == "凝练有力":
        parts.append("任务一项一项推进，节点一个一个落实，成效一件一件检验。")
    elif tone == "务实亲切" and section_index == 0:
        parts.append("立足实际需求，把措施落实到具体事项、具体岗位和具体节点。")
    if section_index == 0:
        style_sentence = _style_sentence(reference_style)
        if style_sentence:
            parts.append(style_sentence)
    if any(label in length for label in ("详细", "长篇", "扩展")):
        parts.append("坚持目标导向和问题导向相统一，及时总结经验、校准偏差，形成常态长效机制。")
    elif any(label in length for label in ("精简", "短篇")):
        parts = parts[:1]
    return "".join(parts)


def _select_fact(facts: list[str], heading: str, section_index: int) -> str:
    if not facts:
        return ""
    if any(word in heading for word in ("问题", "不足", "短板")):
        for fact in facts:
            if any(word in fact for word in ("问题", "不足", "短板", "存在")):
                return fact
    if any(word in heading for word in ("下一步", "安排", "步骤", "要求", "保障")):
        for marker in ("下一步", "计划", "将", "月底", "年前", "启动"):
            for fact in facts:
                if marker in fact:
                    return fact
    if any(word in heading for word in ("成效", "进展", "情况", "做法")):
        measured = [fact for fact in facts if re.search(r"\d", fact)]
        if measured:
            return measured[section_index % len(measured)]
    return facts[section_index % len(facts)]


def _requirement_focus(requirements: str) -> str:
    focuses: list[str] = []
    if any(word in requirements for word in ("时间", "节点", "时限")):
        focuses.append("逐项明确时间节点")
    if any(word in requirements for word in ("责任", "分工", "部门")):
        focuses.append("压实责任分工")
    if any(word in requirements for word in ("数据", "成效", "量化")):
        focuses.append("以材料中的数据检验工作成效")
    if not focuses:
        return ""
    joined = "、".join(focuses)
    return f"按照写作重点，{joined}，确保任务可执行、进度可跟踪、结果可检验。"


def _style_sentence(reference_style: str) -> str:
    if "人民日报" in reference_style:
        return "突出主题主线，以事实支撑判断，以任务回应实际需要。"
    if "光明日报" in reference_style:
        return "既客观看待阶段成效，也深入分析实践中的具体问题和改进空间。"
    if "求是" in reference_style:
        return "坚持认识与实践相统一，在把握总体要求的基础上细化方法路径。"
    return "坚持观点、事实和举措相互支撑，使全文主旨鲜明、层次清楚。"


def _closing(document_type: str, requirements: str) -> str:
    # Requirements guide generation but are never printed as part of a formal document.
    del requirements
    if document_type == "请示":
        default = "以上请示妥否，请批示。"
    elif document_type == "函":
        default = "以上事项，请予支持并函复为盼。"
    elif document_type == "报告":
        default = "特此报告。"
    elif document_type == "通知":
        default = "请结合实际认真抓好贯彻落实。"
    else:
        default = ""
    return default


def _normalize_spacing(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _make_formal(text: str) -> str:
    replacements = {
        "我们": "本单位",
        "弄好": "扎实推进",
        "搞好": "切实做好",
        "很多": "较为突出",
        "马上": "及时",
        "看看": "研究",
        "做到位": "落实到位",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _make_concise(text: str) -> str:
    text = _make_formal(text)
    for phrase in ("需要指出的是，", "众所周知，", "从某种意义上说，", "可以说，", "应该说，"):
        text = text.replace(phrase, "")
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    unique = _dedupe(sentences)
    return "".join(unique)


def _expand(text: str) -> str:
    suffix = "要进一步明确目标任务，细化责任分工，加强过程调度，推动各项措施形成闭环、取得实效。"
    if text.endswith(("。", "！", "？")):
        return f"{text}\n\n{suffix}"
    return f"{text}。\n\n{suffix}"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = ["generate_demo", "review_demo", "rewrite_demo", "supported_document_types"]
