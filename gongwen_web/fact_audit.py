"""Deterministic, traceable fact auditing for official-document drafts.

The engine deliberately uses only local rules.  It extracts atomic material facts,
keeps their source offsets, and maps factual claims in each draft sentence back to
those facts.  It is designed as a conservative editorial aid rather than a semantic
knowledge base: an unverified result means that supporting text was not found in the
supplied material.
"""

# Chinese punctuation in regular expressions and user-facing messages is intentional.
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from gongwen_web.resource_limits import (
    MAX_FACT_AUDIT_CLAIMS,
    MAX_FACT_AUDIT_COMPARISONS,
    MAX_FACT_AUDIT_CONTENT_CHARACTERS,
    MAX_FACT_AUDIT_CONTEXT_CHARACTERS,
    MAX_FACT_AUDIT_FACTS,
    MAX_FACT_AUDIT_MATERIAL_CHARACTERS,
    MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS,
    MAX_FACT_AUDIT_MATERIAL_ITEMS,
    MAX_FACT_AUDIT_MATERIAL_SENTENCES,
    MAX_FACT_AUDIT_MENTIONS_PER_SENTENCE,
    MAX_FACT_AUDIT_SENTENCE_CHARACTERS,
    MAX_FACT_AUDIT_SENTENCES,
    MAX_FACT_AUDIT_TITLE_CHARACTERS,
    MAX_FACT_AUDIT_TOTAL_CHARACTERS,
)

FactKind = Literal["number", "date", "organization", "task"]
AuditStatus = Literal["supported", "partial", "unverified", "contradicted"]
EvidenceRelationship = Literal["supports", "partial", "contradicts"]
IssueLevel = Literal["error", "warning", "suggestion"]


class _AuditModel(BaseModel):
    """Strict-enough response model that remains convenient for a JSON API."""

    model_config = ConfigDict(extra="forbid")


class MaterialFact(_AuditModel):
    """One atomic fact and its exact location in a supplied material."""

    fact_id: str
    kind: FactKind
    value: str
    normalized_value: str
    excerpt: str
    source_index: int = Field(ge=1)
    source_label: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    line: int = Field(ge=1)
    column: int = Field(ge=1)


class EvidenceLink(_AuditModel):
    """A traceable relationship between a draft claim and a material fact."""

    fact_id: str
    relationship: EvidenceRelationship
    confidence: float = Field(ge=0, le=1)
    reason: str


class SentenceClaim(_AuditModel):
    """One claim-like mention detected inside a draft sentence."""

    kind: FactKind
    value: str
    normalized_value: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    status: AuditStatus
    evidence_fact_ids: list[str] = Field(default_factory=list)


class SentenceAudit(_AuditModel):
    """Sentence-to-evidence mapping returned to the editor UI."""

    sentence_id: str
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    line: int = Field(ge=1)
    status: AuditStatus
    has_claim: bool
    claims: list[SentenceClaim] = Field(default_factory=list)
    evidence: list[EvidenceLink] = Field(default_factory=list)


class FactAuditIssue(_AuditModel):
    """One actionable fact-checking observation."""

    level: IssueLevel
    category: str
    message: str
    suggestion: str
    sentence_id: str
    mentions: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)


class FactAuditMetrics(_AuditModel):
    """Coverage and extraction counters for dashboards and quality gates."""

    sentence_count: int = Field(ge=0)
    claim_sentence_count: int = Field(ge=0)
    supported_sentence_count: int = Field(ge=0)
    partial_sentence_count: int = Field(ge=0)
    unverified_sentence_count: int = Field(ge=0)
    contradicted_sentence_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    supported_claim_count: int = Field(ge=0)
    partial_claim_count: int = Field(ge=0)
    unverified_claim_count: int = Field(ge=0)
    contradicted_claim_count: int = Field(ge=0)
    extracted_fact_count: int = Field(ge=0)
    number_fact_count: int = Field(ge=0)
    date_fact_count: int = Field(ge=0)
    organization_fact_count: int = Field(ge=0)
    task_fact_count: int = Field(ge=0)
    referenced_fact_count: int = Field(ge=0)
    evidence_coverage_percent: int = Field(ge=0, le=100)


class FactAuditResult(_AuditModel):
    """Complete deterministic fact-audit result."""

    facts: list[MaterialFact]
    sentences: list[SentenceAudit]
    issues: list[FactAuditIssue]
    metrics: FactAuditMetrics


@dataclass(frozen=True, slots=True)
class _Source:
    index: int
    label: str
    text: str


@dataclass(frozen=True, slots=True)
class _Span:
    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Mention:
    kind: FactKind
    value: str
    normalized_value: str
    start: int
    end: int
    context: str


@dataclass(frozen=True, slots=True)
class _Match:
    status: AuditStatus
    evidence: tuple[EvidenceLink, ...]


@dataclass(frozen=True, slots=True)
class _FactIndex:
    by_kind: dict[FactKind, tuple[MaterialFact, ...]]
    by_exact: dict[tuple[FactKind, str], tuple[MaterialFact, ...]]


@dataclass(slots=True)
class _ComparisonBudget:
    """Per-audit counter preventing unbounded claim-to-fact comparisons."""

    used: int = 0

    def consume(self, candidates: Sequence[MaterialFact]) -> Sequence[MaterialFact]:
        """Charge every candidate or reject before returning a partial answer."""

        if self.used + len(candidates) > MAX_FACT_AUDIT_COMPARISONS:
            raise ValueError(f"事实审校最多执行 {MAX_FACT_AUDIT_COMPARISONS} 次事实匹配")
        self.used += len(candidates)
        return candidates


_SENTENCE_PATTERN = re.compile(r"[^。！？；\r\n]+(?:[。！？；]+|(?=[\r\n])|$)")
_CLAUSE_PATTERN = re.compile(r"[^，,。！？；]+")
_DATE_PATTERN = re.compile(
    r"(?:"
    r"(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])"
    r"|(?:19|20)\d{2}年(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日"
    r"|(?:19|20)\d{2}年(?:0?[1-9]|1[0-2])月"
    r"|(?:19|20)\d{2}年(?:上半年|下半年|第?[一二三四1234]季度|年初|年底)"
    r"|(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日"
    r"|(?:今年|明年|本月|下月|本季度|下季度|年初|年底|月底)"
    r")"
)
_NUMBER_UNIT = (
    r"个百分点|万亿元|亿元|万元|平方公里|平方米|公里|千米|小时|分钟|"
    r"万人次|人次|万人|套|座|所|户|家|个|项|件|次|条|天|人|元|%|％"
)
_NUMBER_PATTERN = re.compile(rf"(?<![\d.])\d[\d,]*(?:\.\d+)?(?:{_NUMBER_UNIT})?")
_ORG_SUFFIX = (
    r"工作领导小组|管理委员会|纪律检查委员会|人民政府|委员会|办公厅|办公室|"
    r"研究院|研究所|服务中心|管理中心|集团|公司|大学|学院|学校|医院|局|厅|"
    r"市委办|政府办|党政办|综合办|项目办|部|委|处|科|中心|单位|部门"
)
_ORG_FOLLOW = (
    r"(?=$|[\s，,。！？；;、：:（）()]|负责|牵头|会同|联合|同步|组织|印发|发布|"
    r"开展|完成|计划|要求|部署|召开|推动|推进|实施|承担|统筹|研究|指出|强调|"
    r"决定|及时|深入|持续|进一步|按照|根据|围绕|聚焦|已|拟|将|应|要|对|于)"
)
_ORG_PATTERN = re.compile(
    rf"[\u4e00-\u9fffA-Za-z0-9·（）()]{{2,36}}?(?:{_ORG_SUFFIX}){_ORG_FOLLOW}"
)
_HEADING_PATTERN = re.compile(
    r"^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[.、])"
)
_TASK_CUES = (
    "完成",
    "开展",
    "建立",
    "制定",
    "实施",
    "落实",
    "整合",
    "建设",
    "改造",
    "组织",
    "报送",
    "审核",
    "复核",
    "检查",
    "印发",
    "出台",
    "压减",
    "缩短",
    "增长",
    "达到",
    "牵头",
    "负责",
    "协同",
    "推动",
    "推进",
    "提升",
)
_GENERIC_ORGANIZATIONS = {
    "单位",
    "部门",
    "有关单位",
    "各单位",
    "各有关单位",
    "有关部门",
    "各部门",
    "各有关部门",
    "本单位",
    "相关单位",
    "相关部门",
    "责任单位",
    "牵头单位",
    "牵头部门",
}
_ORG_PREFIXES = (
    "按照",
    "根据",
    "责成",
    "报送至",
    "移交至",
    "会同",
    "以及",
    "并由",
    "由",
    "请",
)
_TASK_STOP_TERMS = (
    "截至",
    "计划",
    "目前",
    "已经",
    "已",
    "将",
    "应当",
    "应",
    "要",
    "进一步",
    "持续",
    "扎实",
    "全面",
    "切实",
    "相关",
    "有关",
    "各项",
    "工作",
    "任务",
    "要求",
    "按照",
    "根据",
    "确保",
    "于",
    "由",
    "并",
    "和",
    "的",
    "了",
)
_KIND_ORDER: dict[FactKind, int] = {
    "date": 0,
    "number": 1,
    "organization": 2,
    "task": 3,
}


def audit_document(
    *,
    content: str,
    materials: str | Sequence[str],
    title: str = "",
) -> FactAuditResult:
    """Audit a document against user-supplied materials without network access.

    ``title`` participates in stable sentence identifiers and is reserved for future
    title-claim checks; offsets in the returned mappings always refer to ``content``.
    """

    if len(content) > MAX_FACT_AUDIT_CONTENT_CHARACTERS:
        raise ValueError(f"事实审校正文最多 {MAX_FACT_AUDIT_CONTENT_CHARACTERS} 个字符")
    if len(title) > MAX_FACT_AUDIT_TITLE_CHARACTERS:
        raise ValueError(f"事实审校标题最多 {MAX_FACT_AUDIT_TITLE_CHARACTERS} 个字符")
    sources = _coerce_sources(materials)
    if len(content) + sum(len(source.text) for source in sources) > MAX_FACT_AUDIT_TOTAL_CHARACTERS:
        raise ValueError(f"事实审校正文和参考材料合计最多 {MAX_FACT_AUDIT_TOTAL_CHARACTERS} 个字符")
    facts = _extract_material_facts(sources)
    fact_index = _build_fact_index(facts)
    sentence_spans = _sentence_spans(content)
    audits: list[SentenceAudit] = []
    issues: list[FactAuditIssue] = []
    referenced_fact_ids: set[str] = set()
    claim_count = 0
    comparison_budget = _ComparisonBudget()

    for span in sentence_spans:
        mentions = _extract_mentions(span, source_text=content)
        claim_count += len(mentions)
        if claim_count > MAX_FACT_AUDIT_CLAIMS:
            raise ValueError(f"事实审校正文最多识别 {MAX_FACT_AUDIT_CLAIMS} 项事实主张")
        claims: list[SentenceClaim] = []
        evidence: list[EvidenceLink] = []
        for mention in mentions:
            match = _match_mention(mention, fact_index, comparison_budget)
            evidence.extend(match.evidence)
            referenced_fact_ids.update(link.fact_id for link in match.evidence)
            claims.append(
                SentenceClaim(
                    kind=mention.kind,
                    value=mention.value,
                    normalized_value=mention.normalized_value,
                    start=mention.start,
                    end=mention.end,
                    status=match.status,
                    evidence_fact_ids=_dedupe_strings([link.fact_id for link in match.evidence]),
                )
            )

        status = _sentence_status(claims)
        sentence_id = _stable_id("sentence", title, str(span.start), _normalize_text(span.text))
        deduped_evidence = _dedupe_evidence(evidence)
        audit = SentenceAudit(
            sentence_id=sentence_id,
            text=span.text,
            start=span.start,
            end=span.end,
            line=_line_column(content, span.start)[0],
            status=status,
            has_claim=bool(claims),
            claims=claims,
            evidence=deduped_evidence,
        )
        audits.append(audit)
        issues.extend(_issues_for_sentence(audit))

    metrics = _metrics(facts, audits, referenced_fact_ids)
    return FactAuditResult(facts=facts, sentences=audits, issues=issues, metrics=metrics)


def audit_facts(
    materials: str | Sequence[str],
    content: str,
    title: str = "",
) -> FactAuditResult:
    """Convenience alias with positional arguments for service-layer integration."""

    return audit_document(title=title, content=content, materials=materials)


def extract_material_facts(materials: str | Sequence[str]) -> list[MaterialFact]:
    """Expose material extraction separately for ingestion and preview screens."""

    return _extract_material_facts(_coerce_sources(materials))


def _coerce_sources(materials: str | Sequence[str]) -> list[_Source]:
    if isinstance(materials, str):
        values = [materials]
    else:
        if len(materials) > MAX_FACT_AUDIT_MATERIAL_ITEMS:
            raise ValueError(f"事实审校参考材料最多 {MAX_FACT_AUDIT_MATERIAL_ITEMS} 项")
        values = list(materials)
    if len(values) > MAX_FACT_AUDIT_MATERIAL_ITEMS:
        raise ValueError(f"事实审校参考材料最多 {MAX_FACT_AUDIT_MATERIAL_ITEMS} 项")
    text_values = [str(item) for item in values]
    if any(len(text) > MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS for text in text_values):
        raise ValueError(
            f"事实审校单项参考材料最多 {MAX_FACT_AUDIT_MATERIAL_ITEM_CHARACTERS} 个字符"
        )
    if sum(len(text) for text in text_values) > MAX_FACT_AUDIT_MATERIAL_CHARACTERS:
        raise ValueError(f"事实审校参考材料合计最多 {MAX_FACT_AUDIT_MATERIAL_CHARACTERS} 个字符")
    return [
        _Source(index=index, label=f"材料{index}", text=text)
        for index, text in enumerate(text_values, start=1)
        if text.strip()
    ]


def _extract_material_facts(sources: Sequence[_Source]) -> list[MaterialFact]:
    facts: list[MaterialFact] = []
    seen: set[tuple[int, FactKind, int, int, str]] = set()
    sentence_count = 0
    for source in sources:
        remaining_sentences = MAX_FACT_AUDIT_MATERIAL_SENTENCES - sentence_count
        if remaining_sentences <= 0:
            raise ValueError(f"事实审校参考材料句子最多 {MAX_FACT_AUDIT_MATERIAL_SENTENCES} 句")
        source_sentences = _sentence_spans(
            source.text,
            max_sentences=remaining_sentences,
            resource_label="参考材料句子",
            reported_limit=MAX_FACT_AUDIT_MATERIAL_SENTENCES,
        )
        sentence_count += len(source_sentences)
        for sentence in source_sentences:
            for mention in _extract_mentions(sentence, source_text=source.text):
                key = (
                    source.index,
                    mention.kind,
                    mention.start,
                    mention.end,
                    mention.normalized_value,
                )
                if key in seen:
                    continue
                seen.add(key)
                if len(facts) >= MAX_FACT_AUDIT_FACTS:
                    raise ValueError(f"事实审校参考材料最多识别 {MAX_FACT_AUDIT_FACTS} 项事实")
                line, column = _line_column(source.text, mention.start)
                facts.append(
                    MaterialFact(
                        fact_id=_stable_id(
                            "fact",
                            str(source.index),
                            mention.kind,
                            mention.normalized_value,
                            str(mention.start),
                            str(mention.end),
                        ),
                        kind=mention.kind,
                        value=mention.value,
                        normalized_value=mention.normalized_value,
                        excerpt=mention.context,
                        source_index=source.index,
                        source_label=source.label,
                        start=mention.start,
                        end=mention.end,
                        line=line,
                        column=column,
                    )
                )
    facts.sort(key=lambda item: (item.source_index, item.start, _KIND_ORDER[item.kind], item.end))
    return facts


def _sentence_spans(
    text: str,
    *,
    max_sentences: int = MAX_FACT_AUDIT_SENTENCES,
    resource_label: str = "正文句子",
    reported_limit: int | None = None,
) -> list[_Span]:
    spans: list[_Span] = []
    for match in _SENTENCE_PATTERN.finditer(text):
        raw = match.group()
        leading = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if not stripped:
            continue
        if len(stripped) > MAX_FACT_AUDIT_SENTENCE_CHARACTERS:
            raise ValueError(f"事实审校单句最多 {MAX_FACT_AUDIT_SENTENCE_CHARACTERS} 个字符")
        if len(spans) >= max_sentences:
            display_limit = reported_limit if reported_limit is not None else max_sentences
            raise ValueError(f"事实审校{resource_label}最多 {display_limit} 句")
        start = match.start() + leading
        spans.append(_Span(text=stripped, start=start, end=start + len(stripped)))
    return spans


def _extract_mentions(sentence: _Span, *, source_text: str) -> list[_Mention]:
    mentions: list[_Mention] = []

    def add_mention(mention: _Mention) -> None:
        if len(mentions) >= MAX_FACT_AUDIT_MENTIONS_PER_SENTENCE:
            raise ValueError(
                f"事实审校单句最多识别 {MAX_FACT_AUDIT_MENTIONS_PER_SENTENCE} 项事实主张"
            )
        mentions.append(mention)

    occupied_dates: list[tuple[int, int]] = []
    for match in _DATE_PATTERN.finditer(sentence.text):
        start = sentence.start + match.start()
        end = sentence.start + match.end()
        occupied_dates.append((match.start(), match.end()))
        add_mention(
            _Mention(
                kind="date",
                value=source_text[start:end],
                normalized_value=_normalize_date(match.group()),
                start=start,
                end=end,
                context=_context_window(sentence.text, match.start(), match.end()),
            )
        )

    for match in _NUMBER_PATTERN.finditer(sentence.text):
        if any(match.start() < end and match.end() > start for start, end in occupied_dates):
            continue
        value = match.group()
        # Bare one-digit numerals in outline markers are structural rather than factual.
        if not _has_number_unit(value) and len(value.replace(",", "")) == 1:
            continue
        start = sentence.start + match.start()
        end = sentence.start + match.end()
        add_mention(
            _Mention(
                kind="number",
                value=source_text[start:end],
                normalized_value=_normalize_number(value),
                start=start,
                end=end,
                context=_context_window(sentence.text, match.start(), match.end()),
            )
        )

    for match in _ORG_PATTERN.finditer(sentence.text):
        cleaned, relative_start = _clean_organization(match.group())
        if len(cleaned) < 2 or cleaned in _GENERIC_ORGANIZATIONS:
            continue
        start = sentence.start + match.start() + relative_start
        end = start + len(cleaned)
        add_mention(
            _Mention(
                kind="organization",
                value=source_text[start:end],
                normalized_value=_normalize_organization(cleaned),
                start=start,
                end=end,
                context=_context_window(
                    sentence.text,
                    match.start() + relative_start,
                    match.start() + relative_start + len(cleaned),
                ),
            )
        )

    for clause_match in _CLAUSE_PATTERN.finditer(sentence.text):
        raw_clause = clause_match.group()
        leading = len(raw_clause) - len(raw_clause.lstrip())
        value = raw_clause.strip()
        if not value or not _looks_like_task(value):
            continue
        task_start = sentence.start + clause_match.start() + leading
        task_end = task_start + len(value)
        add_mention(
            _Mention(
                kind="task",
                value=value,
                normalized_value=_bounded_text(_normalize_task(value)),
                start=task_start,
                end=task_end,
                context=_context_window(
                    sentence.text,
                    clause_match.start() + leading,
                    clause_match.start() + leading + len(value),
                ),
            )
        )

    mentions.sort(key=lambda item: (item.start, _KIND_ORDER[item.kind], item.end))
    return _dedupe_mentions(mentions)


def _build_fact_index(facts: Sequence[MaterialFact]) -> _FactIndex:
    mutable_by_kind: dict[FactKind, list[MaterialFact]] = {kind: [] for kind in _kinds()}
    mutable_by_exact: dict[tuple[FactKind, str], list[MaterialFact]] = {}
    for fact in facts:
        mutable_by_kind[fact.kind].append(fact)
        mutable_by_exact.setdefault((fact.kind, fact.normalized_value), []).append(fact)
    return _FactIndex(
        by_kind={kind: tuple(items) for kind, items in mutable_by_kind.items()},
        by_exact={key: tuple(items) for key, items in mutable_by_exact.items()},
    )


def _match_mention(
    mention: _Mention,
    index: _FactIndex,
    budget: _ComparisonBudget,
) -> _Match:
    exact = index.by_exact.get((mention.kind, mention.normalized_value), ())
    if exact:
        exact_candidates = budget.consume(exact)
        context_score, best = max(
            (
                (_context_similarity(mention.context, fact.excerpt), fact)
                for fact in exact_candidates
            ),
            key=lambda item: item[0],
        )
        return _Match(
            status="supported",
            evidence=(
                EvidenceLink(
                    fact_id=best.fact_id,
                    relationship="supports",
                    confidence=round(min(1.0, 0.9 + context_score * 0.1), 2),
                    reason="材料中检出相同事实表述。",
                ),
            ),
        )

    candidates = budget.consume(index.by_kind[mention.kind])
    if mention.kind == "organization":
        similar = _best_similarity(mention.normalized_value, candidates)
        if similar is not None and similar[0] >= 0.68:
            score, fact = similar
            return _Match(
                status="partial",
                evidence=(
                    EvidenceLink(
                        fact_id=fact.fact_id,
                        relationship="partial",
                        confidence=round(score, 2),
                        reason="疑似为材料中机构名称的简称或近似写法。",
                    ),
                ),
            )

    if mention.kind == "task":
        similar = _best_task_match(mention.normalized_value, candidates)
        if similar is not None:
            score, fact = similar
            if score >= 0.66:
                return _Match(
                    status="supported",
                    evidence=(
                        EvidenceLink(
                            fact_id=fact.fact_id,
                            relationship="supports",
                            confidence=round(score, 2),
                            reason="任务动作与对象和材料表述高度一致。",
                        ),
                    ),
                )
            if score >= 0.42:
                return _Match(
                    status="partial",
                    evidence=(
                        EvidenceLink(
                            fact_id=fact.fact_id,
                            relationship="partial",
                            confidence=round(score, 2),
                            reason="材料中存在相关任务，但动作、对象或范围未完全对应。",
                        ),
                    ),
                )

    if mention.kind in {"number", "date"}:
        conflict = _best_conflict(mention, candidates)
        if conflict is not None:
            score, fact = conflict
            return _Match(
                status="contradicted",
                evidence=(
                    EvidenceLink(
                        fact_id=fact.fact_id,
                        relationship="contradicts",
                        confidence=round(score, 2),
                        reason="相近语境中的材料记载了不同数值或日期。",
                    ),
                ),
            )

    return _Match(status="unverified", evidence=())


def _best_conflict(
    mention: _Mention, candidates: Sequence[MaterialFact]
) -> tuple[float, MaterialFact] | None:
    ranked: list[tuple[float, MaterialFact]] = []
    for fact in candidates:
        if mention.kind == "number" and not _comparable_numbers(
            mention.normalized_value, fact.normalized_value
        ):
            continue
        score = _context_similarity(mention.context, fact.excerpt)
        threshold = 0.5 if mention.kind == "number" else 0.46
        if score >= threshold:
            ranked.append((score, fact))
    return max(ranked, key=lambda item: item[0]) if ranked else None


def _best_similarity(
    value: str, candidates: Sequence[MaterialFact]
) -> tuple[float, MaterialFact] | None:
    if not candidates:
        return None
    ranked = [(_text_similarity(value, fact.normalized_value), fact) for fact in candidates]
    return max(ranked, key=lambda item: item[0])


def _best_task_match(
    value: str, candidates: Sequence[MaterialFact]
) -> tuple[float, MaterialFact] | None:
    if not candidates:
        return None
    ranked = [(_task_similarity(value, fact.normalized_value), fact) for fact in candidates]
    return max(ranked, key=lambda item: item[0])


def _sentence_status(claims: Sequence[SentenceClaim]) -> AuditStatus:
    if not claims:
        # A structural or purely rhetorical sentence does not require material evidence.
        return "supported"
    statuses = {claim.status for claim in claims}
    if "contradicted" in statuses:
        return "contradicted"
    if statuses == {"supported"}:
        return "supported"
    if "supported" in statuses or "partial" in statuses:
        return "partial"
    return "unverified"


def _issues_for_sentence(sentence: SentenceAudit) -> list[FactAuditIssue]:
    issues: list[FactAuditIssue] = []
    claims_by_status: dict[AuditStatus, list[SentenceClaim]] = {
        "supported": [],
        "partial": [],
        "unverified": [],
        "contradicted": [],
    }
    for claim in sentence.claims:
        claims_by_status[claim.status].append(claim)

    contradicted = claims_by_status["contradicted"]
    if contradicted:
        mentions = _dedupe_strings([claim.value for claim in contradicted])
        fact_ids = _dedupe_strings(
            [fact_id for claim in contradicted for fact_id in claim.evidence_fact_ids]
        )
        issues.append(
            FactAuditIssue(
                level="error",
                category="事实冲突",
                message=f"正文中的 {', '.join(mentions)} 与相近材料表述不一致。",
                suggestion="打开关联材料核对原值、统计口径和时间范围后再定稿。",
                sentence_id=sentence.sentence_id,
                mentions=mentions,
                fact_ids=fact_ids,
            )
        )

    unverified_groups: dict[FactKind, list[SentenceClaim]] = {
        "number": [],
        "date": [],
        "organization": [],
        "task": [],
    }
    for claim in claims_by_status["unverified"]:
        unverified_groups[claim.kind].append(claim)
    labels: dict[FactKind, tuple[str, str]] = {
        "number": ("数字依据", "补充统计表、正式报告或材料原文中的对应数据。"),
        "date": ("日期依据", "补充正式通知、会议纪要或材料原文中的时间依据。"),
        "organization": ("主体依据", "核对机构全称及其在材料中的职责表述。"),
        "task": ("任务依据", "补充任务来源，或将该表述标记为拟议安排供人工确认。"),
    }
    for kind in ("number", "date", "organization", "task"):
        group = unverified_groups[kind]
        if not group:
            continue
        mentions = _dedupe_strings([claim.value for claim in group])
        category, suggestion = labels[kind]
        issues.append(
            FactAuditIssue(
                level="warning",
                category=category,
                message=f"正文中的 {', '.join(mentions)} 未在参考材料中检出依据。",
                suggestion=suggestion,
                sentence_id=sentence.sentence_id,
                mentions=mentions,
            )
        )

    partial = claims_by_status["partial"]
    if partial:
        mentions = _dedupe_strings([claim.value for claim in partial])
        fact_ids = _dedupe_strings(
            [fact_id for claim in partial for fact_id in claim.evidence_fact_ids]
        )
        issues.append(
            FactAuditIssue(
                level="suggestion",
                category="依据待确认",
                message=f"正文中的 {', '.join(mentions)} 仅找到近似材料依据。",
                suggestion="对照关联材料，统一机构名称、任务对象和表述范围。",
                sentence_id=sentence.sentence_id,
                mentions=mentions,
                fact_ids=fact_ids,
            )
        )
    return issues


def _metrics(
    facts: Sequence[MaterialFact],
    sentences: Sequence[SentenceAudit],
    referenced_fact_ids: set[str],
) -> FactAuditMetrics:
    claims = [claim for sentence in sentences for claim in sentence.claims]
    counts = {status: sum(claim.status == status for claim in claims) for status in _statuses()}
    claim_sentence_count = sum(sentence.has_claim for sentence in sentences)
    sentence_counts = {
        status: sum(sentence.has_claim and sentence.status == status for sentence in sentences)
        for status in _statuses()
    }
    weighted_supported = counts["supported"] + counts["partial"] * 0.5
    coverage = round(100 * weighted_supported / len(claims)) if claims else 100
    kind_counts = {kind: sum(fact.kind == kind for fact in facts) for kind in _kinds()}
    return FactAuditMetrics(
        sentence_count=len(sentences),
        claim_sentence_count=claim_sentence_count,
        supported_sentence_count=sentence_counts["supported"],
        partial_sentence_count=sentence_counts["partial"],
        unverified_sentence_count=sentence_counts["unverified"],
        contradicted_sentence_count=sentence_counts["contradicted"],
        claim_count=len(claims),
        supported_claim_count=counts["supported"],
        partial_claim_count=counts["partial"],
        unverified_claim_count=counts["unverified"],
        contradicted_claim_count=counts["contradicted"],
        extracted_fact_count=len(facts),
        number_fact_count=kind_counts["number"],
        date_fact_count=kind_counts["date"],
        organization_fact_count=kind_counts["organization"],
        task_fact_count=kind_counts["task"],
        referenced_fact_count=len(referenced_fact_ids),
        evidence_coverage_percent=coverage,
    )


def _normalize_date(value: str) -> str:
    compact = value.strip().replace(".", "-").replace("/", "-")
    iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", compact)
    if iso:
        return f"{iso.group(1)}-{int(iso.group(2)):02d}-{int(iso.group(3)):02d}"
    chinese_day = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", compact)
    if chinese_day:
        return (
            f"{chinese_day.group(1)}-{int(chinese_day.group(2)):02d}-"
            f"{int(chinese_day.group(3)):02d}"
        )
    chinese_month = re.fullmatch(r"(\d{4})年(\d{1,2})月", compact)
    if chinese_month:
        return f"{chinese_month.group(1)}-{int(chinese_month.group(2)):02d}"
    month_day = re.fullmatch(r"(\d{1,2})月(\d{1,2})日", compact)
    if month_day:
        return f"--{int(month_day.group(1)):02d}-{int(month_day.group(2)):02d}"
    return compact


def _context_window(text: str, start: int, end: int) -> str:
    """Return bounded local context around one mention."""

    if len(text) <= MAX_FACT_AUDIT_CONTEXT_CHARACTERS:
        return text
    midpoint = max(start, min(len(text), (start + end) // 2))
    window_start = midpoint - MAX_FACT_AUDIT_CONTEXT_CHARACTERS // 2
    window_start = max(0, min(window_start, len(text) - MAX_FACT_AUDIT_CONTEXT_CHARACTERS))
    return text[window_start : window_start + MAX_FACT_AUDIT_CONTEXT_CHARACTERS]


def _bounded_text(value: str) -> str:
    """Bound normalized task values while preserving both ends."""

    if len(value) <= MAX_FACT_AUDIT_CONTEXT_CHARACTERS:
        return value
    head = MAX_FACT_AUDIT_CONTEXT_CHARACTERS // 2
    tail = MAX_FACT_AUDIT_CONTEXT_CHARACTERS - head
    return f"{value[:head]}{value[-tail:]}"


def _normalize_number(value: str) -> str:
    normalized = value.replace(",", "").replace("％", "%").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(.*)", normalized)
    if match is None:
        return normalized
    numeric = match.group(1).rstrip("0").rstrip(".") if "." in match.group(1) else match.group(1)
    return f"{numeric}|{match.group(2)}"


def _has_number_unit(value: str) -> bool:
    return re.search(rf"(?:{_NUMBER_UNIT})$", value) is not None


def _clean_organization(value: str) -> tuple[str, int]:
    start = 0
    for marker in _ORG_PREFIXES:
        position = (
            value.rfind(marker) if len(marker) > 1 else (0 if value.startswith(marker) else -1)
        )
        if position >= 0:
            candidate_start = position + len(marker)
            if candidate_start < len(value):
                start = max(start, candidate_start)
    cleaned = value[start:].lstrip("，、：:；;和及")
    start += len(value[start:]) - len(value[start:].lstrip("，、：:；;和及"))
    return cleaned, start


def _normalize_organization(value: str) -> str:
    return re.sub(r"[\s（）()]", "", value)


def _normalize_task(value: str) -> str:
    result = _DATE_PATTERN.sub("", value)
    result = _NUMBER_PATTERN.sub("", result)
    for term in _TASK_STOP_TERMS:
        result = result.replace(term, "")
    return _normalize_text(result)


def _normalize_context(value: str) -> str:
    result = _DATE_PATTERN.sub("日期", value)
    result = _NUMBER_PATTERN.sub("数值", result)
    for term in ("目前", "截至", "计划", "已经", "已", "将", "应", "于", "了", "的"):
        result = result.replace(term, "")
    return _normalize_text(result)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff%]", "", value).casefold()


def _looks_like_task(value: str) -> bool:
    normalized = value.strip()
    if _HEADING_PATTERN.match(normalized) and len(normalized) <= 24:
        return False
    return any(cue in normalized for cue in _TASK_CUES)


def _context_similarity(left: str, right: str) -> float:
    return _text_similarity(
        _normalize_context(_bounded_text(left)),
        _normalize_context(_bounded_text(right)),
    )


def _task_similarity(left: str, right: str) -> float:
    bounded_left = _bounded_text(left)
    bounded_right = _bounded_text(right)
    text_score = _text_similarity(bounded_left, bounded_right)
    left_cues = {cue for cue in _TASK_CUES if cue in bounded_left}
    right_cues = {cue for cue in _TASK_CUES if cue in bounded_right}
    cue_score = (
        len(left_cues & right_cues) / len(left_cues | right_cues)
        if left_cues or right_cues
        else 0.0
    )
    return text_score * 0.8 + cue_score * 0.2


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if len(left) >= 4 and len(right) >= 4 and (left in right or right in left):
        return min(len(left), len(right)) / max(len(left), len(right))
    left_pairs = _bigrams(left)
    right_pairs = _bigrams(right)
    if not left_pairs or not right_pairs:
        return len(set(left) & set(right)) / len(set(left) | set(right))
    return 2 * len(left_pairs & right_pairs) / (len(left_pairs) + len(right_pairs))


def _bigrams(value: str) -> set[str]:
    return {value[index : index + 2] for index in range(len(value) - 1)}


def _comparable_numbers(left: str, right: str) -> bool:
    left_unit = left.partition("|")[2]
    right_unit = right.partition("|")[2]
    if left_unit == right_unit:
        return True
    percentage_units = {"%", "个百分点"}
    return left_unit in percentage_units and right_unit in percentage_units


def _line_column(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    previous_newline = text.rfind("\n", 0, offset)
    return line, offset - previous_newline


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _dedupe_mentions(mentions: Sequence[_Mention]) -> list[_Mention]:
    result: list[_Mention] = []
    seen: set[tuple[FactKind, int, int, str]] = set()
    for mention in mentions:
        key = (mention.kind, mention.start, mention.end, mention.normalized_value)
        if key not in seen:
            seen.add(key)
            result.append(mention)
    return result


def _dedupe_evidence(evidence: Sequence[EvidenceLink]) -> list[EvidenceLink]:
    result: list[EvidenceLink] = []
    positions: dict[tuple[str, EvidenceRelationship], int] = {}
    for link in evidence:
        key = (link.fact_id, link.relationship)
        position = positions.get(key)
        if position is None:
            positions[key] = len(result)
            result.append(link)
        elif link.confidence > result[position].confidence:
            result[position] = link
    return result


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _statuses() -> tuple[AuditStatus, ...]:
    return ("supported", "partial", "unverified", "contradicted")


def _kinds() -> tuple[FactKind, ...]:
    return ("number", "date", "organization", "task")


__all__ = [
    "AuditStatus",
    "EvidenceLink",
    "FactAuditIssue",
    "FactAuditMetrics",
    "FactAuditResult",
    "FactKind",
    "MaterialFact",
    "SentenceAudit",
    "SentenceClaim",
    "audit_document",
    "audit_facts",
    "extract_material_facts",
]
