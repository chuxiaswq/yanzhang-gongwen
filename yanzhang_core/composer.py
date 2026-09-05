"""Provider-neutral composition for the general Yanzhang writing platform.

The composer has a deterministic local path and an optional injected live-model
callback.  It owns prompt construction and closed response validation, while
provider construction and all network I/O remain at the application boundary.
"""

# Chinese writing prompts and deterministic copy intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from yanzhang_core.models import (
    Channel,
    ContentBlock,
    ContentBlockKind,
    CoreModel,
    KnowledgeItem,
    TextAsset,
    WritingBrief,
)
from yanzhang_core.packs import RecipeDefinition, RecipeSection
from yanzhang_core.scenario_profiles import get_scenario_profile, scenario_for_document_type

type CompositionMode = Literal["local", "live"]

_MAX_KNOWLEDGE_CHARACTERS = 100_000
_MAX_MODEL_RESPONSE_CHARACTERS = 1_000_000
_SPACE = re.compile(r"[ \t\f\v]+")


class ModelTextCallback(Protocol):
    """Minimal async boundary implemented by an application model gateway."""

    async def __call__(self, system_prompt: str, user_prompt: str, /) -> str: ...


class CompositionError(ValueError):
    """Base error for a rejected composition request or model result."""


class ModelCallbackRequiredError(CompositionError):
    """Raised when live composition is requested without an injected gateway."""


class ModelCompositionOutputError(CompositionError):
    """Raised when a live-model response does not satisfy the closed contract."""


class ComposedDraft(CoreModel):
    """A validated draft ready for persistence as a text asset."""

    brief_id: str = Field(min_length=1, max_length=128)
    recipe_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    blocks: tuple[ContentBlock, ...] = Field(min_length=1, max_length=10_000)
    mode: CompositionMode


class _LiveModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class _LiveSection(_LiveModel):
    id: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=200_000)


class _LiveDraft(_LiveModel):
    title: str = Field(min_length=1, max_length=300)
    sections: tuple[_LiveSection, ...] = Field(min_length=1, max_length=24)


class _LiveVariantBlock(_LiveModel):
    kind: ContentBlockKind
    text: str = Field(min_length=1, max_length=200_000)
    heading_level: int | None = Field(default=None, ge=1, le=6)

    @model_validator(mode="after")
    def validate_heading_level(self) -> Self:
        if self.kind == "heading" and self.heading_level is None:
            raise ValueError("heading block requires heading_level")
        if self.kind != "heading" and self.heading_level is not None:
            raise ValueError("only heading blocks accept heading_level")
        return self


class _LiveVariant(_LiveModel):
    title: str = Field(min_length=1, max_length=300)
    blocks: tuple[_LiveVariantBlock, ...] = Field(min_length=1, max_length=10_000)


class YanzhangComposer:
    """Compose master drafts and channel variants without vendor coupling."""

    def __init__(
        self,
        model_callback: ModelTextCallback | None = None,
        *,
        max_knowledge_characters: int = _MAX_KNOWLEDGE_CHARACTERS,
    ) -> None:
        if max_knowledge_characters < 1 or max_knowledge_characters > 1_000_000:
            raise ValueError("max_knowledge_characters 应在 1 到 1000000 之间")
        self._model_callback = model_callback
        self._max_knowledge_characters = max_knowledge_characters

    @property
    def live_available(self) -> bool:
        """Whether a live-model callback was injected by the application."""

        return self._model_callback is not None

    async def invoke_model(self, system_prompt: str, user_prompt: str) -> str:
        """Invoke the injected provider-neutral callback for a closed task contract.

        Higher-level application services use this narrow boundary for model-assisted
        operations, such as review, that do not create a composed draft.  Provider
        construction and network I/O remain outside the core package.
        """

        callback = self._require_callback()
        return await callback(system_prompt, user_prompt)

    async def compose(
        self,
        brief: WritingBrief,
        recipe: RecipeDefinition,
        knowledge: Sequence[KnowledgeItem] = (),
        *,
        live: bool = False,
        title: str | None = None,
    ) -> ComposedDraft:
        """Create a master draft from one validated brief and recipe."""

        self._validate_recipe(brief, recipe)
        selected_title = _clean_title(title or brief.title)
        bounded_knowledge = self._bounded_knowledge(knowledge)
        if live:
            callback = self._require_callback()
            system_prompt, user_prompt = _composition_prompts(
                brief,
                recipe,
                bounded_knowledge,
                title=selected_title,
            )
            raw_output = await callback(system_prompt, user_prompt)
            payload = _parse_model_payload(raw_output, _LiveDraft)
            blocks = _blocks_from_live_draft(
                payload,
                brief=brief,
                recipe=recipe,
                expected_title=selected_title,
                knowledge=bounded_knowledge,
            )
            mode: CompositionMode = "live"
        else:
            blocks = _deterministic_blocks(
                brief,
                recipe,
                bounded_knowledge,
                title=selected_title,
            )
            mode = "local"
        return ComposedDraft(
            brief_id=brief.id,
            recipe_id=recipe.id,
            title=selected_title,
            blocks=blocks,
            mode=mode,
        )

    async def create_variant(
        self,
        source: TextAsset,
        *,
        target_channel: Channel,
        instruction: str = "",
        live: bool = False,
        title: str | None = None,
    ) -> ComposedDraft:
        """Adapt an existing asset into another channel-specific draft."""

        selected_title = _clean_title(title or source.title)
        clean_instruction = _normalize_text(instruction)[:2_000]
        if live:
            callback = self._require_callback()
            system_prompt, user_prompt = _variant_prompts(
                source,
                target_channel=target_channel,
                instruction=clean_instruction,
                title=selected_title,
            )
            raw_output = await callback(system_prompt, user_prompt)
            payload = _parse_model_payload(raw_output, _LiveVariant)
            blocks = _blocks_from_live_variant(
                payload,
                source=source,
                expected_title=selected_title,
            )
            mode: CompositionMode = "live"
        else:
            blocks = _deterministic_variant_blocks(
                source,
                target_channel=target_channel,
                instruction=clean_instruction,
            )
            mode = "local"
        return ComposedDraft(
            brief_id=source.brief_id,
            recipe_id=f"variant-{target_channel}",
            title=selected_title,
            blocks=blocks,
            mode=mode,
        )

    def _require_callback(self) -> ModelTextCallback:
        if self._model_callback is None:
            raise ModelCallbackRequiredError("实时写作模式尚未配置模型回调")
        return self._model_callback

    def _bounded_knowledge(
        self,
        knowledge: Sequence[KnowledgeItem],
    ) -> tuple[KnowledgeItem, ...]:
        items = tuple(knowledge)
        ids = tuple(item.id for item in items)
        if len(ids) != len(set(ids)):
            raise CompositionError("knowledge item id 不得重复")
        total = sum(len(item.content) for item in items)
        if total > self._max_knowledge_characters:
            raise CompositionError(
                f"写作知识内容合计超过 {self._max_knowledge_characters} 字符上限"
            )
        return items

    @staticmethod
    def _validate_recipe(brief: WritingBrief, recipe: RecipeDefinition) -> None:
        if recipe.id != brief.recipe_id:
            raise CompositionError("写作简报与配方标识不一致")
        if recipe.pack_id != brief.scenario_pack_id:
            raise CompositionError("写作简报与场景包标识不一致")
        if brief.channel not in recipe.channels:
            raise CompositionError("所选配方不支持写作简报指定的输出渠道")


# Templates describe a section's actual job rather than repeating a generic
# introduction. Bracketed slots are deliberately not presented as finished facts.
_SECTION_COPY: dict[str, dict[str, str]] = {
    "work-email": {
        "subject": "关于{topic}：{goal}",
        "context": (
            "{audience}，您好。此次沟通希望{goal}。核心结论：【待补充：需收件人了解或确认的事项】。"
        ),
        "details": "以下信息用于支持本次判断：【待补充：必要背景、当前状态与相关附件】。",
        "action": (
            "请确认【待补充：具体请求】；"
            "回复对象与期望时间为【待确认】。材料中未确认的承诺暂不列入。"
        ),
    },
    "weekly-report": {
        "done": "本周围绕{topic}记录实际交付。已完成事项：【待补充：成果及验收记录】。",
        "progress": "进行中的事项按当前状态、剩余工作和下一节点逐项列明。进度：【待补充】。",
        "risks": "需协同的问题应说明影响、所需支持和处理状态。当前阻塞：【待确认：风险记录】。",
        "next": "下周优先处理【待确认：任务及交付物】，负责人和时间依据已确认的排期填写。",
    },
    "business-proposal": {
        "problem": (
            "本方案讨论{topic}。需要解决的业务问题是【待补充：问题表现、影响对象与现有成本】。"
        ),
        "goal": "方案目标为{goal}。验收标准与资源边界：【待确认】。",
        "solution": (
            "候选路径需比较投入、依赖和可交付成果。推荐方案及其理由：【待补充：方案比较依据】。"
        ),
        "value": (
            "预期价值属于测算而非既有成绩。计算口径、假设与基准值："
            "【待补充】，暂不填写未经验证的收益数字。"
        ),
        "risk": "推进前需核对资源、依赖及主要失败条件。试点安排与停止条件：【待确认】。",
    },
    "meeting-followup": {
        "decisions": (
            "关于{topic}，仅将会议明确确认的事项列为决定。已确认结论：【待补充：会议记录定位】。"
        ),
        "actions": (
            "行动项按“任务—负责人—期限—状态”列示。"
            "缺少负责人或时间的项目标记为【待确认】，不代拟承诺。"
        ),
        "dependencies": "记录执行所依赖的前置条件与协作支持。阻塞及影响：【待补充】。",
        "confirm": "尚未形成决议的问题：【待补充】。请相关人员核对原始讨论后确认。",
    },
    "presentation-outline": {
        "message": "本次演示围绕{topic}，希望{audience}{goal}。主张：【待补充：一句核心结论】。",
        "storyline": (
            "信息顺序为：需要解决的问题、支持判断的证据、可比较的选择。各环节材料：【待补充】。"
        ),
        "slides": "每页保留一个结论式标题，配以必要证据或图表。逐页要点及图表来源：【待补充】。",
        "close": "最后明确需要听众作出的决定或反馈。决策请求与后续安排：【待确认】。",
    },
    "press-release": {
        "headline": "{topic}",
        "lead": (
            "本稿报道{topic}。事件主体、发生时间、地点及最新进展：【待补充：已核实新闻事实】。"
        ),
        "body": "按新闻重要程度展开已核实细节。采访引语仅使用原始记录，发言者及出处：【待补充】。",
        "background": (
            "用于理解事件的相关背景：【待补充：公开资料及时间范围】。背景说明与当次事件分开陈述。"
        ),
    },
    "wechat-article": {
        "hook": "关于{topic}，这篇文章想帮{audience}厘清一个具体问题：{goal}。",
        "context": (
            "先从读者可能遇到的情境切入。场景与问题：【待补充：真实案例或明确标注的假设情境】。"
        ),
        "value": "区分已知事实、作者解读与可尝试的方法。核心信息：【待补充：支撑观点的材料】。",
        "close": (
            "读到这里，可先核对{topic}中与自身最相关的一项信息。进一步了解的资料入口：【待补充】。"
        ),
    },
    "social-post": {
        "hook": "聊聊{topic}：{goal}。",
        "message": "这次只分享一个重点：【待补充：实际体验、观点及必要依据】。",
        "action": "如果你也关注{topic}，欢迎交流具体问题与经验。",
    },
    "short-video-script": {
        "hook": "关于{topic}，你最想弄清楚什么？这一段先讲{goal}。",
        "beats": (
            "口播先交代问题，再给必要信息，最后解释理由。各节拍内容：【待补充：可核实材料】。"
        ),
        "turn": "需要特别区分的是事实本身与对事实的解释。关键差异：【待补充】。",
        "cta": "想继续了解{topic}，可查看【待补充：材料入口】或留下具体问题。",
    },
    "literature-review": {
        "scope": "本综述聚焦{topic}，拟回答{goal}。概念界定、检索范围与文献纳入标准：【待补充】。",
        "themes": (
            "文献按研究问题、理论视角与研究方法组织，而非逐篇罗列。"
            "主题分组及对应文献：【待补充：来源与页码】。"
        ),
        "debate": (
            "对相关研究的比较应区分结论、样本、方法及适用条件。"
            "共同证据与分歧：【待补充：逐项对应的文献依据】。"
        ),
        "gap": (
            "研究空白需建立在实际检索与证据比较之上。尚未充分回答的问题："
            "【待论证】，不以“首次”“填补空白”代替文献核查。"
        ),
    },
    "research-outline": {
        "question": (
            "围绕{topic}，拟将{goal}转化为边界明确、可回答的研究问题。"
            "研究对象与问题表述：【待补充】。"
        ),
        "framework": (
            "核心概念、理论关系与分析单位：【待补充：定义及来源】。假设仅作为待检验命题。"
        ),
        "method": (
            "资料来源、获取条件、样本范围与分析方法："
            "【待确认】。研究设计与已完成的研究工作分开描述。"
        ),
        "chapters": (
            "章节依次服务于问题提出、文献与框架、资料分析和讨论。"
            "各章需要的证据及论证任务：【待补充】。"
        ),
    },
    "research-abstract": {
        "background": (
            "本研究关注{topic}，研究目的为{goal}。背景问题与研究范围：【待补充：原文对应内容】。"
        ),
        "method": "方法：【待补充：原文中的研究设计、样本与分析方法】。未提供的方法不推测补写。",
        "result": "结果：【待补充：原文已报告的主要发现及数据】。暂不推断方向、显著性或因果关系。",
        "conclusion": "结论：【待补充：由原文结果支持的解释】。适用范围与限制应与研究设计一致。",
    },
    "reviewer-response": {
        "thanks": (
            "感谢审稿人对{topic}提出的建议。以下按原始意见逐条整理回复，修改状态以实际稿件为准。"
        ),
        "responses": (
            "审稿意见：【待粘贴原文】。回应：【待补充："
            "处理理由与证据】。不将计划修改表述为已经完成。"
        ),
        "changes": (
            "修改内容与定位：【待核对：章节、页码、段落及修改前后文本】。确认后再列入回复。"
        ),
        "open": (
            "仍需讨论的意见：【待确认】。如有不同判断，"
            "应说明依据与方法边界，并保持尊重、具体的表达。"
        ),
    },
}

# Small lexical groups route excerpts conservatively. They never infer that a
# plan is completed or that a supplied number is a research result.
_SECTION_ANCHORS: dict[str, tuple[str, ...]] = {
    "done": ("完成", "交付", "验收", "上线"),
    "progress": ("进行", "当前", "进度", "正在", "进展"),
    "results": ("完成", "成果", "下降", "增长", "成效"),
    "problems": ("问题", "不足", "风险", "重复"),
    "risks": ("风险", "阻塞", "问题", "依赖", "延期"),
    "next": ("下周", "计划", "下一步", "拟", "将"),
    "action": ("请", "确认", "回复", "截止"),
    "actions": ("负责", "期限", "完成", "任务"),
    "method": ("方法", "样本", "访谈", "实验", "检索", "数据集"),
    "result": ("结果", "发现", "显著", "置信", "效应"),
    "conclusion": ("结论", "限制", "局限", "适用"),
    "debate": ("分歧", "相比", "差异", "研究发现", "结果"),
    "gap": ("不足", "局限", "尚未", "空白"),
    "responses": ("意见", "审稿", "建议"),
    "changes": ("修改", "页", "段落", "章节"),
}


def _deterministic_blocks(
    brief: WritingBrief,
    recipe: RecipeDefinition,
    knowledge: tuple[KnowledgeItem, ...],
    *,
    title: str,
) -> tuple[ContentBlock, ...]:
    blocks: list[ContentBlock] = []
    facts = tuple(item for item in knowledge if item.kind != "style_reference")
    assignments = _section_excerpts(recipe.sections, facts, academic=recipe.pack_id == "academic")
    for section_index, section in enumerate(recipe.sections):
        blocks.append(
            ContentBlock(
                id=_stable_id("block", brief.id, title, section.id, "heading"),
                kind="heading",
                order=len(blocks),
                text=section.title,
                heading_level=1,
            )
        )
        selected = assignments[section_index]
        paragraph = _deterministic_paragraph(brief, recipe, section, selected)
        blocks.append(
            ContentBlock(
                id=_stable_id("block", brief.id, title, section.id, paragraph),
                kind="paragraph",
                order=len(blocks),
                text=paragraph,
                knowledge_item_ids=tuple(dict.fromkeys(item.id for item, _ in selected)),
            )
        )
    constraints = tuple(
        clause
        for value in brief.constraints
        if (clause := _normalize_text(value).rstrip("。！？；;，,. "))
    )
    if constraints:
        text = "写作约定（交付前核对）：" + "；".join(constraints) + "。"
        blocks.append(
            ContentBlock(
                id=_stable_id("block", brief.id, title, "constraints", text),
                kind="callout",
                order=len(blocks),
                text=text,
            )
        )
    return tuple(blocks)


_ACADEMIC_PACK_MARKER = "【已导入学术材料包】"
_ACADEMIC_EVIDENCE_BLOCK = re.compile(
    r"^\[证据[ \t]+[^\]\n]+\][ \t]*[^\n]*(?:\n(?!\[(?:文献|证据)[ \t])[^\n]*)*",
    re.MULTILINE,
)
_ACADEMIC_METADATA_LINE = re.compile(r"^\[文献[ \t]+[^\]\n]+\][^\n]*", re.MULTILINE)


def _academic_material_units(content: str) -> tuple[str, ...]:
    """Prioritize real imported snippets and exclude bibliographic boilerplate.

    The web workspace currently serializes its typed EvidenceSnippet records
    into one bounded KnowledgeItem. Preserve each marked evidence block as one
    unit rather than letting preceding metadata fill all paragraph slots. The
    explicit marker is a data-format delimiter, never an instruction to execute.
    """

    prefix, marker, package = content.partition(_ACADEMIC_PACK_MARKER)
    if not marker:
        return tuple(re.findall(r"[^。！？\n]+[。！？]?", content))
    snippets = tuple(match.group(0).strip() for match in _ACADEMIC_EVIDENCE_BLOCK.finditer(package))
    # This known built-in example is writing-task guidance, not research data.
    context = "" if prefix.lstrip().startswith("示例任务：") else prefix
    contextual_units = tuple(re.findall(r"[^。！？\n]+[。！？]?", context))
    return (*snippets, *contextual_units)


def _academic_metadata(content: str) -> tuple[str, ...]:
    _, marker, package = content.partition(_ACADEMIC_PACK_MARKER)
    if not marker:
        return ()
    return tuple(match.group(0).strip() for match in _ACADEMIC_METADATA_LINE.finditer(package))


def _bounded_material_excerpt(raw: str, *, academic: bool, limit: int = 480) -> str:
    """Bound snippet prose, not its identity or original source locator.

    A bounded excerpt is not a complete quotation. Keep the annotation outside
    the original prose and explicitly disclose truncation before displaying it.
    """

    text = _normalize_text(raw)
    header_match = re.match(r"^\[证据[ \t]+[^\]\n]+\]", text) if academic else None
    if header_match is None:
        return _excerpt(text, limit=limit)
    header = header_match.group(0)
    body = text[header_match.end() :].strip()
    locator_match = re.search(r"(?:^|\n)(定位[：:][^\n]*)$", body)
    locator = locator_match.group(1) if locator_match is not None else ""
    if locator_match is not None:
        body = body[: locator_match.start()].rstrip()
    if len(body) <= limit:
        return text
    excerpt = _excerpt(body, limit=limit)
    disclosure = "【原文节选提示：下文已截断，不代表完整引文；请回查原始证据及上下文。】"
    parts = (header, disclosure, excerpt, locator)
    return "\n".join(part for part in parts if part)


def _section_excerpts(
    sections: tuple[RecipeSection, ...],
    facts: tuple[KnowledgeItem, ...],
    *,
    academic: bool = False,
) -> tuple[tuple[tuple[KnowledgeItem, str], ...], ...]:
    assignments: list[list[tuple[KnowledgeItem, str]]] = [[] for _ in sections]
    seen: set[str] = set()
    # Collect marked research evidence across *all* materials before contextual
    # notes so that early metadata or long task descriptions cannot exhaust the
    # limited excerpt slots. A snippet stays atomic, including its source IDs.
    material_units = [
        (item, unit)
        for item in facts
        for unit in (
            _academic_material_units(item.content)
            if academic
            else tuple(re.findall(r"[^。！？\n]+[。！？]?", item.content))
        )
    ]
    if academic:
        material_units.sort(key=lambda pair: not pair[1].startswith("[证据 "))
    for item, raw in material_units:
        text = _bounded_material_excerpt(raw, academic=academic)
        if not text or text in seen:
            continue
        seen.add(text)
        scores = [sum(term in text for term in _SECTION_ANCHORS.get(s.id, ())) for s in sections]
        best = max(scores, default=0)
        if best:
            index = min(
                (i for i, score in enumerate(scores) if score == best),
                key=lambda i: (len(assignments[i]), i),
            )
        else:
            # Unclassified facts remain together as context, not fabricated
            # as section-specific results, conclusions or commitments.
            index = next(
                (
                    i
                    for i, section in enumerate(sections)
                    if section.id
                    in {
                        "details",
                        "context",
                        "scope",
                        "overview",
                        "body",
                        "themes",
                        "background",
                    }
                ),
                0,
            )
        if len(assignments[index]) < 3:
            assignments[index].append((item, text))
    return tuple(tuple(group) for group in assignments)


def _deterministic_paragraph(
    brief: WritingBrief,
    recipe: RecipeDefinition,
    section: RecipeSection,
    references: tuple[tuple[KnowledgeItem, str], ...],
) -> str:
    template = _SECTION_COPY.get(recipe.id, {}).get(section.id)
    if template is None:
        template = "{section}：{purpose}所需事实与依据：【待补充】。"
    paragraph = template.format(
        topic=brief.title,
        goal=brief.goal.rstrip("。！？；;，,. "),
        audience=brief.audience,
        section=section.title,
        purpose=_sentence(section.purpose),
    )
    if references:
        excerpts = "\n".join(f"材料提要《{item.title}》：{text}" for item, text in references)
        paragraph += "\n" + excerpts
    return _normalize_text(paragraph)


def _blocks_from_live_draft(
    payload: _LiveDraft,
    *,
    brief: WritingBrief,
    recipe: RecipeDefinition,
    expected_title: str,
    knowledge: tuple[KnowledgeItem, ...],
) -> tuple[ContentBlock, ...]:
    if payload.title != expected_title:
        raise ModelCompositionOutputError("模型结果改变了已确认标题")
    expected_ids = tuple(section.id for section in recipe.sections)
    returned_ids = tuple(section.id for section in payload.sections)
    if returned_ids != expected_ids:
        raise ModelCompositionOutputError("模型结果未按写作配方返回完整有序章节")
    knowledge_ids = tuple(
        item.id
        for item in knowledge
        if item.kind != "style_reference"
        and (recipe.pack_id != "academic" or _academic_material_units(item.content))
    )
    blocks: list[ContentBlock] = []
    for definition, section in zip(recipe.sections, payload.sections, strict=True):
        blocks.append(
            ContentBlock(
                id=_stable_id("block", brief.id, expected_title, definition.id, "heading"),
                kind="heading",
                order=len(blocks),
                text=definition.title,
                heading_level=1,
            )
        )
        blocks.append(
            ContentBlock(
                id=_stable_id("block", brief.id, expected_title, definition.id, section.content),
                kind="paragraph",
                order=len(blocks),
                text=section.content,
                knowledge_item_ids=knowledge_ids,
            )
        )
    return tuple(blocks)


def _deterministic_variant_blocks(
    source: TextAsset,
    *,
    target_channel: Channel,
    instruction: str,
) -> tuple[ContentBlock, ...]:
    source_text = source.plain_text()
    if target_channel == "social":
        texts: tuple[tuple[ContentBlockKind, str, int | None], ...] = (
            ("paragraph", _excerpt(source_text, limit=600), None),
        )
    elif target_channel == "presentation":
        summaries = tuple(
            _excerpt(block.text, limit=160)
            for block in source.blocks
            if block.kind != "title" and block.text
        )[:12]
        texts = tuple(("list", f"• {summary}", None) for summary in summaries)
    elif target_channel == "email":
        academic = scenario_for_document_type(source.content_type).id == "academic"
        texts = (
            (
                "paragraph",
                f"您好，随信分享《{source.title}》的{'研究材料' if academic else '相关信息'}。",
                None,
            ),
            ("paragraph", _excerpt(source_text, limit=2_000), None),
            (
                "action_item",
                "希望获得的反馈：【待确认：研究问题、论证或修改建议】。"
                if academic
                else "需要您确认的事项：【待补充：具体请求】；期望回复时间：【待确认】。",
                None,
            ),
        )
    elif target_channel == "academic":
        texts = (
            ("heading", "问题与材料范围", 1),
            (
                "paragraph",
                f"本材料围绕《{source.title}》整理已有信息，尚不据此宣称完成了独立研究。",
                None,
            ),
            ("heading", "已有内容与证据", 1),
            ("paragraph", _excerpt(source_text, limit=4_000), None),
            ("heading", "待核查的论证与引用", 1),
            (
                "paragraph",
                "研究问题、方法、结果与引文需逐项回查原始材料。资料未包含的研究结论和参考文献保留为【待补充】。",
                None,
            ),
        )
    elif target_channel == "meeting":
        texts = (
            ("heading", "供讨论的信息", 1),
            ("paragraph", _excerpt(source_text, limit=2_000), None),
            ("heading", "待确认事项", 1),
            (
                "action_item",
                "请核对需讨论的问题及决定；原稿未明确的负责人、期限与任务状态均标记为【待确认】。",
                None,
            ),
        )
    elif target_channel == "web":
        texts = (
            ("paragraph", _excerpt(source_text, limit=480), None),
            *(
                (block.kind, block.text, block.heading_level)
                for block in source.blocks
                if block.kind != "title" and block.text
            ),
        )
    else:
        texts = tuple(
            (block.kind, block.text, block.heading_level) for block in source.blocks if block.text
        )
    if instruction:
        texts = (*texts, ("callout", f"调整要求：{instruction}", None))
    if not texts:
        texts = (("paragraph", "【待补充：渠道版本正文】", None),)
    return tuple(
        ContentBlock(
            id=_stable_id("variant", source.id, target_channel, str(order), text),
            kind=kind,
            order=order,
            text=text,
            heading_level=heading_level,
        )
        for order, (kind, text, heading_level) in enumerate(texts)
    )


def _blocks_from_live_variant(
    payload: _LiveVariant,
    *,
    source: TextAsset,
    expected_title: str,
) -> tuple[ContentBlock, ...]:
    if payload.title != expected_title:
        raise ModelCompositionOutputError("模型结果改变了已确认标题")
    return tuple(
        ContentBlock(
            id=_stable_id("variant", source.id, str(order), block.kind, block.text),
            kind=block.kind,
            order=order,
            text=block.text,
            heading_level=block.heading_level,
        )
        for order, block in enumerate(payload.blocks)
    )


def _composition_prompts(
    brief: WritingBrief,
    recipe: RecipeDefinition,
    knowledge: tuple[KnowledgeItem, ...],
    *,
    title: str,
) -> tuple[str, str]:
    system_prompt = (
        "你是砚章写作引擎。仅输出一个JSON对象，不得输出Markdown。"
        "对象必须且只能包含title和sections；sections每项必须且只能包含id和content。"
        "严格使用给定章节id及顺序，标题保持不变。事实、数字、日期、名称和引文只能来自"
        "给定事实材料；依据不足时使用【待补充】。写法参考只用于结构、语气和句式特征，"
        "不得把其中事实写入成稿。不同章节承担不同论证任务，不重复抄写任务简报或硬性约束。"
        "bibliographic_metadata仅用于识别来源，不是研究证据；学术主张应来自knowledge中的原文片段。"
        + "场景写作要求："
        + "；".join(get_scenario_profile(recipe.pack_id).prompt_guidance)
    )
    fact_knowledge = tuple(item for item in knowledge if item.kind != "style_reference")
    style_references = tuple(item for item in knowledge if item.kind == "style_reference")
    request = {
        "brief": brief.model_dump(mode="json"),
        "scenario": get_scenario_profile(recipe.pack_id).model_dump(mode="json"),
        "title": title,
        "recipe": {
            "id": recipe.id,
            "sections": [
                {"id": section.id, "title": section.title, "purpose": section.purpose}
                for section in recipe.sections
            ],
            "fact_strategy": recipe.fact_strategy,
        },
        "knowledge": [
            {
                "id": item.id,
                "title": item.title,
                "kind": item.kind,
                "content": "\n\n".join(_academic_material_units(item.content))
                if recipe.pack_id == "academic"
                else item.content,
            }
            for item in fact_knowledge
            if recipe.pack_id != "academic" or _academic_material_units(item.content)
        ],
        "bibliographic_metadata": [
            {"knowledge_item_id": item.id, "records": list(_academic_metadata(item.content))}
            for item in fact_knowledge
            if recipe.pack_id == "academic" and _academic_metadata(item.content)
        ],
        "style_references": [
            {
                "id": item.id,
                "title": item.title,
                "content": item.content,
            }
            for item in style_references
        ],
    }
    return system_prompt, json.dumps(request, ensure_ascii=False, separators=(",", ":"))


def _variant_prompts(
    source: TextAsset,
    *,
    target_channel: Channel,
    instruction: str,
    title: str,
) -> tuple[str, str]:
    system_prompt = (
        "你是砚章渠道改编引擎。仅输出一个JSON对象，不得输出Markdown。"
        "对象必须且只能包含title和blocks；每个block必须且只能包含kind、text、"
        "heading_level。标题保持不变，不新增原稿没有的事实。"
        + "来源场景要求："
        + "；".join(scenario_for_document_type(source.content_type).prompt_guidance)
        + "目标为学术渠道时，采用问题、依据与边界的表达，不将宣传性判断改写成研究结论。"
    )
    request = {
        "title": title,
        "target_channel": target_channel,
        "instruction": instruction,
        "source": source.model_dump(mode="json"),
    }
    return system_prompt, json.dumps(request, ensure_ascii=False, separators=(",", ":"))


def _parse_model_payload[T: BaseModel](raw_output: str, model: type[T]) -> T:
    text = raw_output.strip()
    if len(text) > _MAX_MODEL_RESPONSE_CHARACTERS:
        raise ModelCompositionOutputError("模型结果超过 1000000 字符上限")
    if text.startswith("```") and text.endswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 : -3].strip() if first_newline >= 0 else ""
    try:
        return model.model_validate_json(text)
    except (ValidationError, ValueError):
        raise ModelCompositionOutputError("模型结果未通过结构化写作契约校验") from None


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _clean_title(value: str) -> str:
    title = _normalize_text(value)
    if not title:
        raise CompositionError("标题不能为空")
    if len(title) > 300:
        raise CompositionError("标题最多 300 个字符")
    return title


def _sentence(value: str) -> str:
    text = _normalize_text(value)
    return text if text.endswith(("。", "！", "？", "；")) else text + "。"


def _excerpt(value: str, *, limit: int) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip("，,；;。 ") + "…"


def _normalize_text(value: str) -> str:
    lines = tuple(_SPACE.sub(" ", line).strip() for line in value.replace("\r", "\n").split("\n"))
    return "\n".join(line for line in lines if line).strip()


__all__ = [
    "ComposedDraft",
    "CompositionError",
    "CompositionMode",
    "ModelCallbackRequiredError",
    "ModelCompositionOutputError",
    "ModelTextCallback",
    "YanzhangComposer",
]
