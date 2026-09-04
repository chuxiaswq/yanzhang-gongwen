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
from yanzhang_core.packs import RecipeDefinition

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


def _deterministic_blocks(
    brief: WritingBrief,
    recipe: RecipeDefinition,
    knowledge: tuple[KnowledgeItem, ...],
    *,
    title: str,
) -> tuple[ContentBlock, ...]:
    blocks: list[ContentBlock] = []
    fact_knowledge = tuple(item for item in knowledge if item.kind != "style_reference")
    for section_index, section in enumerate(recipe.sections):
        heading_order = len(blocks)
        blocks.append(
            ContentBlock(
                id=_stable_id("block", brief.id, title, section.id, "heading"),
                kind="heading",
                order=heading_order,
                text=section.title,
                heading_level=1,
            )
        )
        reference = fact_knowledge[section_index % len(fact_knowledge)] if fact_knowledge else None
        paragraph = _deterministic_paragraph(
            brief,
            section_title=section.title,
            section_purpose=section.purpose,
            reference=reference,
            first=section_index == 0,
        )
        blocks.append(
            ContentBlock(
                id=_stable_id("block", brief.id, title, section.id, paragraph),
                kind="paragraph",
                order=len(blocks),
                text=paragraph,
                knowledge_item_ids=(reference.id,) if reference is not None else (),
            )
        )
    return tuple(blocks)


def _deterministic_paragraph(
    brief: WritingBrief,
    *,
    section_title: str,
    section_purpose: str,
    reference: KnowledgeItem | None,
    first: bool,
) -> str:
    prefix = (
        f"围绕“{brief.title}”，面向{brief.audience}，重点实现{_sentence(brief.goal)}"
        if first
        else f"围绕{section_title}，{_sentence(section_purpose)}"
    )
    if reference is None:
        evidence = "具体事实、数据、时间和责任主体请按【待补充】标记补齐。"
    else:
        excerpt = _excerpt(reference.content, limit=480)
        evidence = f"参考《{reference.title}》所载材料：{excerpt}"
    constraints = ""
    if brief.constraints:
        clauses = tuple(
            clause
            for value in brief.constraints
            if (clause := _normalize_text(value).rstrip("。！？；;，,. "))
        )
        if clauses:
            constraints = " 写作时同时遵循：" + "；".join(clauses) + "。"
    return _normalize_text(prefix + evidence + constraints)


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
    knowledge_ids = tuple(item.id for item in knowledge if item.kind != "style_reference")
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
        texts = (
            ("paragraph", f"您好：现将“{source.title}”有关内容说明如下。", None),
            ("paragraph", _excerpt(source_text, limit=2_000), None),
            ("action_item", "请结合实际确认后续安排与完成时间。", None),
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
        "不得把其中事实写入成稿。"
    )
    fact_knowledge = tuple(item for item in knowledge if item.kind != "style_reference")
    style_references = tuple(item for item in knowledge if item.kind == "style_reference")
    request = {
        "brief": brief.model_dump(mode="json"),
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
                "content": item.content,
            }
            for item in fact_knowledge
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
