"""Deterministic writing, rewriting, and review engines for the local demo."""

# Chinese punctuation is intentional in generated official-document copy.
# ruff: noqa: RUF001

from __future__ import annotations

import re
from dataclasses import dataclass

from gongwen_web.methodologies import resolve_content_methodology
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
    generate_titles_demo,
    score_title,
    title_request_from_generate,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；])|[\r\n]+")
_HEADING = re.compile(r"^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[.、])")
_PLACEHOLDER = re.compile(
    r"(?:\{\{[^{}]+\}\}|\[[A-Z][A-Z0-9_]*\]|"
    r"【[^】]*(?:待补|日期|单位|姓名|金额|时间|地点|部门|事项)[^】]*】)"
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


@dataclass(frozen=True, slots=True)
class DocumentSpec:
    """Title and outline recipe for one writing scenario."""

    title_pattern: str
    headings: tuple[str, ...]


_SPECS: dict[str, DocumentSpec] = {
    "通知": DocumentSpec(
        "关于{topic}的通知",
        ("一、明确总体要求", "二、聚焦重点任务", "三、强化组织保障"),
    ),
    "请示": DocumentSpec("关于{topic}的请示", ("一、基本情况", "二、主要考虑", "三、请示事项")),
    "报告": DocumentSpec(
        "关于{topic}的报告",
        ("一、总体情况", "二、主要做法与成效", "三、存在问题", "四、下一步安排"),
    ),
    "函": DocumentSpec("关于{topic}的函", ("一、有关情况", "二、商洽事项", "三、办理建议")),
    "会议纪要": DocumentSpec(
        "{topic}会议纪要", ("一、会议基本情况", "二、议定事项", "三、落实要求")
    ),
    "工作总结": DocumentSpec(
        "{topic}工作总结",
        ("一、总体情况", "二、主要做法和成效", "三、问题与不足", "四、下一步工作"),
    ),
    "实施方案": DocumentSpec(
        "{topic}实施方案",
        ("一、总体要求", "二、目标任务", "三、重点举措", "四、实施步骤", "五、保障措施"),
    ),
    "讲话稿": DocumentSpec(
        "在{topic}会议上的讲话",
        ("一、提高站位，凝聚思想共识", "二、突出重点，推动任务落实", "三、压实责任，确保取得实效"),
    ),
    "汇报材料": DocumentSpec(
        "关于{topic}的汇报",
        ("一、工作进展", "二、特色做法", "三、短板问题", "四、下步考虑"),
    ),
}

_GENERIC_SPEC = DocumentSpec(
    "关于{topic}的材料", ("一、总体情况", "二、重点工作", "三、下一步安排")
)

_STYLE_NOTES = {
    "权威媒体综合写法": "标题准确凝练，论述由背景到举措层层推进，小标题保持结构平行。",
    "人民日报式消息评论": "突出主题主线，开篇点题，事实与观点衔接紧密，结尾落到行动。",
    "光明日报式理性阐释": "重视背景解释和逻辑展开，表达平实克制，兼顾事实与分析。",
    "求是式理论论证": "先明确核心判断，再分层论证方法路径，强调逻辑完整和实践指向。",
}


def supported_document_types() -> tuple[str, ...]:
    """Return document types in their intended UI order."""

    return tuple(_SPECS)


def generate_demo(request: GenerateRequest) -> GeneratedDocument:
    """Build a complete, repeatable Chinese official-document draft."""

    document_type, _ = _resolve_spec(request.document_type)
    topic = _clean_topic(request.topic)
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
            label=request.reference_style,
            excerpt=_STYLE_NOTES.get(request.reference_style, _STYLE_NOTES["权威媒体综合写法"]),
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
    blocks: list[str] = []
    if request.audience and document_type in {"通知", "请示", "报告", "函"}:
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
    headings = [line for line in paragraphs if _HEADING.match(line)]
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
                suggestion="补充由事由和文种构成的完整标题。",
            )
        )
    if len(content) < 180:
        issues.append(
            ReviewIssue(
                level="suggestion",
                category="完整性",
                message="正文篇幅较短，论述可能不够充分。",
                suggestion="核对背景、任务、责任和时限是否齐全。",
            )
        )
    if not headings:
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
                suggestion="尽量补充责任主体、完成时限或量化标准。",
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


def _resolve_spec(value: str) -> tuple[str, DocumentSpec]:
    normalized = value.strip()
    aliases = {"纪要": "会议纪要", "总结": "工作总结", "方案": "实施方案", "讲话": "讲话稿"}
    normalized = aliases.get(normalized, normalized)
    return normalized, _SPECS.get(normalized, _GENERIC_SPEC)


def _clean_topic(value: str) -> str:
    topic = value.strip().rstrip("。；，")
    for prefix in ("关于", "围绕"):
        if topic.startswith(prefix) and len(topic) > len(prefix) + 2:
            topic = topic[len(prefix) :]
    for suffix in ("的通知", "的请示", "的报告", "实施方案", "工作总结"):
        if topic.endswith(suffix) and len(topic) > len(suffix) + 2:
            topic = topic[: -len(suffix)]
    return topic.strip()


def _title_candidates(document_type: str, topic: str, spec: DocumentSpec) -> list[TitleCandidate]:
    standard = spec.title_pattern.format(topic=topic)
    if document_type == "会议纪要":
        options = [
            (standard, "标准纪要", "直接标明会议主题和文种"),
            (f"{topic}专题会议纪要", "专题聚焦", "适合围绕单项议题形成的纪要"),
            (f"{topic}工作推进会会议纪要", "推进部署", "适合包含任务分工的推进会议"),
            (f"研究推进{topic}工作会议纪要", "事项明确", "突出会议研究事项"),
            (f"{topic}协调会议纪要", "协同办理", "适合跨部门协调事项"),
        ]
    elif document_type in {"通知", "请示", "报告", "函"}:
        options = [
            (standard, "要素完整", "由事由和文种构成，适合正式流转"),
            (f"关于扎实推进{topic}工作的{document_type}", "执行导向", "强调工作落实"),
            (f"关于进一步做好{topic}有关工作的{document_type}", "稳健规范", "适合延续性工作"),
            (f"关于加强{topic}工作统筹的{document_type}", "协同推进", "突出统筹协调"),
            (f"关于{topic}重点事项的{document_type}", "重点聚焦", "适合聚焦具体事项"),
        ]
    else:
        options = [
            (standard, "稳健规范", "要素完整，适合工作材料和归档"),
            (f"聚焦重点任务 推动{topic}提质增效", "凝练概括", "突出主线和工作成效"),
            (f"以实干实绩推动{topic}落地见效", "部署有力", "强调执行导向和结果导向"),
            (f"抓重点 破难点 推动{topic}取得新成效", "并列对仗", "适合汇报和讲话场景"),
            (f"守正创新促提升 实干担当开新局——{topic}", "主副标题", "适合总结和汇报材料"),
        ]
    seen: set[str] = set()
    candidates: list[TitleCandidate] = []
    for title, style, reason in options:
        if title in seen:
            continue
        seen.add(title)
        candidates.append(
            TitleCandidate(title=title, style=style, reason=reason, selected=not candidates)
        )
    return candidates


def _material_facts(material: str) -> list[str]:
    if not material:
        return []
    facts: list[str] = []
    for part in _SENTENCE_SPLIT.split(material):
        cleaned = re.sub(r"^[\s•·\-—\d.、]+", "", part.strip())
        if len(cleaned) < 4:
            continue
        if cleaned[-1] not in "。！？；":
            cleaned += "。"
        facts.append(cleaned)
        if len(facts) == 8:
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
    text = re.sub(r"[ \t]+", "", text)
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
