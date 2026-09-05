"""Shared application service for the Yanzhang Web and MCP surfaces.

The service coordinates provider-neutral domain components.  Every blocking
repository/export operation is moved off the caller's event loop, and model or
metadata connector calls happen only after repository transactions have ended.
"""

# Chinese public messages intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import html
import io
import json
from collections.abc import Mapping, Sequence
from concurrent.futures import Future
from dataclasses import asdict, is_dataclass
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gongwen_web.docx import build_docx_from_blocks, unique_filename
from gongwen_web.runtime import RuntimeSettings
from yanzhang_academic import (
    AcademicRepository,
    AcademicService,
    BibliographicRecord,
    ClaimCitationLink,
    JournalProfile,
    ResearchBrief,
    ResearchClaim,
    ReviewComment,
    manuscript_word_count,
)
from yanzhang_core.composer import ModelTextCallback, YanzhangComposer
from yanzhang_core.exporters import (
    ExportDependencyError,
)
from yanzhang_core.exporters import (
    ExportFormat as CoreExportFormat,
)
from yanzhang_core.exporters import (
    export_asset as export_core_asset,
)
from yanzhang_core.headlines import CandidateFactContext, CandidateRequest, generate_candidates
from yanzhang_core.knowledge import KnowledgeRepository, KnowledgeSearchResult
from yanzhang_core.models import (
    Channel,
    ContentBlock,
    Evidence,
    KnowledgeItem,
    ProjectTerm,
    Revision,
    TextAsset,
    WritingBrief,
    WritingProject,
)
from yanzhang_core.packs import (
    RecipeDefinition,
    RecipeSection,
    get_recipe,
    get_scenario_pack,
    list_recipes,
    list_scenario_packs,
)
from yanzhang_core.parsers import parse_document, supported_import_formats
from yanzhang_core.plugins import ExtensionDiscoveryReport, ExtensionRegistry
from yanzhang_core.provenance import (
    ProvenanceGraph,
    attach_material_evidence,
    build_provenance_graph,
    evidence_from_material,
)
from yanzhang_core.reviews import ReviewReport, review_asset
from yanzhang_core.routing import (
    ModelExecutionConfigurationError,
    ModelRouteRequest,
    RoutingDecision,
    RoutingPresetName,
    route_model,
)
from yanzhang_core.storage import (
    BriefConflictError,
    RecordNotFoundError,
    WorkflowRunRecord,
    WritingStorage,
)
from yanzhang_core.workflow import (
    StepContext,
    StepResult,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowStateError,
    WorkflowStepDefinition,
)

type RequestInput = BaseModel | Mapping[str, object]
type PlatformResult = dict[str, object]
type ExportFormat = Literal["docx", "pdf", "markdown", "text", "html", "latex", "csv"]
type ReviewDimension = Literal[
    "evidence",
    "logic",
    "clarity",
    "audience_tone",
    "language",
    "format",
]
type ReviewSeverity = Literal["info", "warning", "error"]

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_MIME_TYPES: dict[ExportFormat, str] = {
    "docx": _DOCX_MIME,
    "pdf": "application/pdf",
    "markdown": "text/markdown; charset=utf-8",
    "text": "text/plain; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "latex": "application/x-latex",
    "csv": "text/csv; charset=utf-8",
}
_SUFFIXES: dict[ExportFormat, str] = {
    "docx": ".docx",
    "pdf": ".pdf",
    "markdown": ".md",
    "text": ".txt",
    "html": ".html",
    "latex": ".tex",
    "csv": ".csv",
}
_WORKFLOW_DEFINITION = WorkflowDefinition(
    id="yanzhang-writing",
    version="2",
    steps=(
        WorkflowStepDefinition(id="research", handler="yanzhang.research"),
        WorkflowStepDefinition(id="titles", handler="yanzhang.titles"),
        WorkflowStepDefinition(id="outline", handler="yanzhang.outline"),
        WorkflowStepDefinition(id="draft", handler="yanzhang.compose", max_attempts=2),
        WorkflowStepDefinition(id="review", handler="yanzhang.review"),
        WorkflowStepDefinition(id="export", handler="yanzhang.export"),
    ),
)

_REVIEW_DIMENSIONS: tuple[ReviewDimension, ...] = (
    "evidence",
    "logic",
    "clarity",
    "audience_tone",
    "language",
    "format",
)
_REVIEW_CHECK_DIMENSIONS: dict[str, frozenset[ReviewDimension]] = {
    "structure": frozenset({"logic", "format"}),
    "style": frozenset({"clarity", "audience_tone", "language"}),
    "facts": frozenset({"evidence"}),
    "citations": frozenset({"evidence"}),
    "terminology": frozenset({"language"}),
}
_REVIEW_PENALTIES: dict[ReviewSeverity, int] = {"info": 3, "warning": 10, "error": 25}


class _LiveReviewIssue(BaseModel):
    """One bounded issue returned by the optional model review pass."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    dimension: ReviewDimension
    severity: ReviewSeverity
    block_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1_000)
    suggestion: str = Field(min_length=1, max_length=1_000)


class _LiveReviewPayload(BaseModel):
    """Closed response contract for the model-assisted review pass."""

    model_config = ConfigDict(extra="forbid")

    issues: tuple[_LiveReviewIssue, ...] = Field(default=(), max_length=128)


class ArtifactWriter(Protocol):
    """Local binary/text artifact boundary used by both transports."""

    def put(
        self,
        data: bytes | bytearray | memoryview,
        *,
        filename: str,
        mime: str,
        ttl_seconds: int | None = None,
        project_id: str | None = None,
        asset_id: str | None = None,
        revision_id: str | None = None,
        creator: str = "gongwen_v1",
    ) -> object: ...


class YanzhangPlatformService:
    """Concrete asynchronous platform consumed by Web routes and MCP tools."""

    def __init__(
        self,
        storage: WritingStorage,
        *,
        knowledge: KnowledgeRepository | None = None,
        workflow_engine: WorkflowEngine | None = None,
        composer: YanzhangComposer | None = None,
        model_callback: ModelTextCallback | None = None,
        academic: AcademicService | None = None,
        academic_repository: AcademicRepository | None = None,
        artifact_store: ArtifactWriter,
        routing_preset: RoutingPresetName = "local_only",
        runtime: RuntimeSettings | None = None,
        extension_registry: ExtensionRegistry | None = None,
        extension_discovery: ExtensionDiscoveryReport | None = None,
    ) -> None:
        if composer is not None and model_callback is not None:
            raise ValueError("composer 与 model_callback 只需注入一项")
        self.storage = storage
        self.knowledge = knowledge or KnowledgeRepository(storage)
        self.composer = composer or YanzhangComposer(model_callback)
        self.academic = academic or AcademicService()
        self.academic_repository = academic_repository or AcademicRepository(storage)
        self.artifact_store = artifact_store
        self.routing_preset = routing_preset
        self.runtime = runtime
        self.extension_registry = extension_registry or ExtensionRegistry()
        self.extension_discovery = extension_discovery or ExtensionDiscoveryReport()
        self.workflow_engine = workflow_engine or WorkflowEngine(storage)
        self._owns_workflow_engine = workflow_engine is None
        self._background_futures: set[Future[WorkflowRunRecord]] = set()
        for name, handler in (
            ("yanzhang.research", self._workflow_research),
            ("yanzhang.titles", self._workflow_titles),
            ("yanzhang.outline", self._workflow_outline),
            ("yanzhang.compose", self._workflow_compose),
            ("yanzhang.review", self._workflow_review),
            ("yanzhang.export", self._workflow_export),
        ):
            self.workflow_engine.register_step(name, handler, replace=True)

    def close(self, *, wait: bool = True) -> None:
        """Release the owned workflow executor; injected engines remain caller-owned."""

        if self._owns_workflow_engine:
            self.workflow_engine.close(wait=wait)

    async def yanzhang_get_status(self, request: RequestInput) -> PlatformResult:
        _payload(request)
        await asyncio.to_thread(self.storage.check_ready)
        await asyncio.to_thread(self.academic_repository.check_ready)
        decision = self._route(None, request_live=False)
        return {
            "ok": True,
            "service": "yanzhang-platform",
            "api_version": "v2",
            "storage": "ready",
            "academic_storage": "ready",
            "live_model_available": self.composer.live_available,
            "routing_preset": self.routing_preset,
            "resolved_route": _model(decision),
            "execution": self._execution(False),
            "model": (
                self.runtime.public_model_configuration()
                if self.runtime is not None
                else {
                    "server_provider_configured": False,
                    "provider_name": None,
                    "default_model": None,
                    "default_mode": "demo",
                    "demo_engine": "deterministic",
                    "demo_uses_model": False,
                }
            ),
            "scenario_pack_count": len(list_scenario_packs()),
            "recipe_count": len(list_recipes()),
            "import_formats": list(supported_import_formats()),
            "export_formats": list(_MIME_TYPES),
            "academic_connectors": list(self.academic.list_connectors()),
            "extensions": {
                kind: list(names) for kind, names in self.extension_registry.catalog().items()
            },
            "extension_discovery": {
                "loaded": list(self.extension_discovery.loaded),
                "skipped": list(self.extension_discovery.skipped),
                "error_count": len(self.extension_discovery.errors),
            },
        }

    async def yanzhang_list_scene_packs(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        channel = _optional_str(values, "channel")
        content_type = _optional_str(values, "content_type")
        packs: list[dict[str, object]] = []
        for pack in list_scenario_packs():
            recipes = [
                recipe
                for recipe in pack.recipes
                if (channel is None or channel in recipe.channels)
                and (content_type is None or recipe.content_type == content_type)
            ]
            if not recipes:
                continue
            item = _model(pack)
            item["recipes"] = [_model(recipe) for recipe in recipes]
            packs.append(item)
        return {"items": packs, "count": len(packs)}

    async def yanzhang_get_scene_pack(self, request: RequestInput) -> PlatformResult:
        pack = get_scenario_pack(_required_str(_payload(request), "pack_id"))
        return {"pack": _model(pack)}

    async def yanzhang_create_project(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        pack_id = _required_str(values, "scenario_pack_id", default="gongwen")
        get_scenario_pack(pack_id)
        project = await asyncio.to_thread(
            self.storage.create_project,
            _required_str(values, "name"),
            description=_required_str(values, "description", default=""),
            tags=_str_sequence(values, "tags"),
            default_pack_id=pack_id,
        )
        return {"project": _model(project)}

    async def yanzhang_list_projects(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        limit, offset = _page(values)
        projects = await self._all_projects()
        query = (_optional_str(values, "query") or "").casefold()
        pack_id = _optional_str(values, "scenario_pack_id")
        filtered = [
            project
            for project in projects
            if (not query or query in f"{project.name}\n{project.description}".casefold())
            and (pack_id is None or project.default_pack_id == pack_id)
        ]
        page = filtered[offset : offset + limit]
        return {
            "items": [_model(project) for project in page],
            "count": len(page),
            "total": len(filtered),
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(page) < len(filtered),
        }

    async def yanzhang_get_project(self, request: RequestInput) -> PlatformResult:
        project = await self._project(_required_str(_payload(request), "project_id"))
        return {"project": _model(project)}

    async def yanzhang_upsert_project_term(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        payload: dict[str, object] = {
            "project_id": project_id,
            "term": _required_str(values, "term"),
            "preferred_form": _required_str(values, "preferred_form"),
            "description": _required_str(values, "description", default=""),
            "discouraged_variants": _str_sequence(values, "discouraged_variants"),
        }
        term_id = _optional_str(values, "term_id")
        if term_id is not None:
            payload["id"] = term_id
        term = ProjectTerm.model_validate(payload)
        saved = await asyncio.to_thread(self.storage.save_project_term, term)
        return {"term": _model(saved)}

    async def yanzhang_list_project_terms(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        limit, offset = _page(values)
        terms = await asyncio.to_thread(self.storage.list_project_terms, project_id)
        page = terms[offset : offset + limit]
        return {
            "items": [_model(term) for term in page],
            "count": len(page),
            "total": len(terms),
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(page) < len(terms),
        }

    async def yanzhang_delete_project_term(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        term_id = _required_str(values, "term_id")
        await self._project(project_id)
        deleted = await asyncio.to_thread(
            self.storage.delete_project_term,
            term_id,
            project_id=project_id,
        )
        if not deleted:
            raise RecordNotFoundError(f"project term not found: {term_id}")
        return {"deleted": True, "project_id": project_id, "term_id": term_id}

    async def yanzhang_add_material(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        payload: dict[str, object] = {
            "project_id": project_id,
            "title": _required_str(values, "title"),
            "content": _required_str(values, "content"),
            "kind": _required_str(values, "kind", default="source"),
            "source_url": _required_str(values, "source_url", default=""),
            "tags": _str_sequence(values, "tags"),
        }
        material_id = _optional_str(values, "material_id")
        if material_id is not None:
            payload["id"] = material_id
        item = KnowledgeItem.model_validate(payload)
        saved = await asyncio.to_thread(self.knowledge.upsert_item, item)
        return {"material": _model(saved)}

    async def yanzhang_list_materials(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        limit, offset = _page(values)
        items = await self._all_materials(project_id, kind=_optional_str(values, "kind"))
        tags = set(_str_sequence(values, "tags"))
        query = (_optional_str(values, "query") or "").casefold()
        filtered = [
            item
            for item in items
            if (not tags or tags.issubset(item.tags))
            and (
                not query
                or query in f"{item.title}\n{item.content}\n{' '.join(item.tags)}".casefold()
            )
        ]
        page = filtered[offset : offset + limit]
        return {
            "items": [_material_summary(item) for item in page],
            "count": len(page),
            "total": len(filtered),
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(page) < len(filtered),
        }

    async def yanzhang_get_material(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        item = await self._material(
            _required_str(values, "project_id"), _required_str(values, "material_id")
        )
        start = _integer(values, "chunk_offset", default=0)
        size = _integer(values, "chunk_size", default=8_000)
        payload = _model(item)
        payload["content"] = item.content[start : start + size]
        payload["chunk_offset"] = start
        payload["chunk_size"] = len(cast(str, payload["content"]))
        payload["has_more"] = start + size < len(item.content)
        payload["total_characters"] = len(item.content)
        payload["next_offset"] = min(start + size, len(item.content))
        return {"material": payload}

    async def yanzhang_search(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        query = _required_str(values, "query")
        scope = _required_str(values, "scope", default="all")
        limit, offset = _page(values)
        results: list[dict[str, object]] = []
        if scope in {"all", "materials"}:
            matches = await self._all_material_matches(project_id, query)
            tags = set(_str_sequence(values, "tags"))
            results.extend(
                {
                    "scope": "materials",
                    "id": match.item.id,
                    "title": match.item.title,
                    "score": match.score,
                    "excerpt": match.excerpt,
                }
                for match in matches
                if not tags or tags.issubset(match.item.tags)
            )
        if scope in {"all", "assets"}:
            assets = await self._all_assets(project_id)
            needle = query.casefold()
            results.extend(
                {
                    "scope": "assets",
                    "id": asset.id,
                    "title": asset.title,
                    "score": 1.0,
                    "excerpt": _excerpt(asset.plain_text(), query),
                }
                for asset in assets
                if needle in f"{asset.title}\n{asset.plain_text()}".casefold()
            )
        if scope in {"all", "literature"}:
            records = await self._all_academic_records(project_id, query=query)
            results.extend(
                {
                    "scope": "literature",
                    "id": record.id,
                    "title": record.title,
                    "score": 1.0,
                    "excerpt": record.abstract[:500],
                }
                for record in records
            )
        page = results[offset : offset + limit]
        return {
            "items": page,
            "count": len(page),
            "total": len(results),
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(page) < len(results),
        }

    async def create_brief(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        brief = self._brief(values)
        await self._validate_material_ids(project_id, brief.knowledge_item_ids)
        try:
            saved = await asyncio.to_thread(self.storage.save_brief, brief, project_id=project_id)
        except BriefConflictError:
            raise BriefConflictError("stable brief id is already bound to other content") from None
        return {"brief": _model(saved), "brief_id": saved.id}

    async def yanzhang_generate_titles(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        brief = self._brief(values)
        materials = await self._materials(project_id, brief.knowledge_item_ids)
        fact_materials = _fact_materials(materials)
        requested_count = _integer(values, "count", default=8)
        candidate_request = CandidateRequest.model_validate(
            {
                "brief": brief.model_dump(mode="json"),
                "kind": _required_str(values, "headline_kind", default="title"),
                "count": requested_count,
                "required_terms": _str_sequence(values, "keywords")[:16],
                "formula_ids": _str_sequence(values, "formula_ids"),
                "fact_contexts": [
                    CandidateFactContext(
                        material_id=item.id,
                        title=item.title,
                        excerpt=item.content[:4_000],
                    )
                    for item in fact_materials[:16]
                ],
            }
        )
        batch = await asyncio.to_thread(generate_candidates, candidate_request)
        return {
            "candidate_batch": _model(batch),
            "requested_count": requested_count,
            "generation_mode": "local",
            "execution": self._execution(False),
            "context_usage": {
                "factual_material_ids": [item.id for item in fact_materials[:16]],
                "excluded_style_reference_count": len(materials) - len(fact_materials),
                "fact_excerpt_limit": 4_000,
            },
        }

    async def yanzhang_create_workflow(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        brief = self._brief(values)
        await self._validate_material_ids(project_id, brief.knowledge_item_ids)
        requested_brief_id = _optional_str(values, "brief_id")
        if requested_brief_id is None:
            await asyncio.to_thread(self.storage.save_brief, brief, project_id=project_id)
        else:
            saved_brief = await self._brief_for_project(project_id, requested_brief_id)
            if saved_brief != brief:
                raise ValueError("已保存简报与当前工作流输入不一致，请先保存新的任务简报")
            brief = saved_brief
        requested_live = _boolean(values, "live", default=False)
        decision = self._route(brief.model_profile_id, request_live=requested_live)
        live = self._live_mode(requested_live, decision)
        run = await asyncio.to_thread(
            self.workflow_engine.create_run,
            _WORKFLOW_DEFINITION,
            {
                "brief": brief.model_dump(mode="json"),
                "project_id": project_id,
                "auto_review": _boolean(values, "auto_review", default=True),
                "requested_exports": list(_str_sequence(values, "requested_exports")),
                "live": live,
                "execution": self._execution(live),
                "resolved_route": _model(decision),
            },
            project_id=project_id,
        )
        return {
            "workflow": await self._workflow_payload(run),
            "brief_id": brief.id,
            "resolved_route": _model(decision),
            "execution": self._execution(live),
        }

    async def yanzhang_run_workflow(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        run_id = _required_str(values, "workflow_id")
        run = await asyncio.to_thread(
            self.workflow_engine.get_run,
            run_id,
            project_id=project_id,
        )
        mode = _required_str(values, "mode", default="sync")
        if mode not in {"sync", "background"}:
            raise ValueError("mode 应为 sync 或 background")
        resume_from = _optional_str(values, "resume_from")
        status = run["status"]
        if status in {"succeeded", "cancelled"}:
            if resume_from is not None:
                await asyncio.to_thread(
                    self.workflow_engine.validate_resume_from,
                    run_id,
                    resume_from,
                    project_id=project_id,
                )
            return {"workflow": await self._workflow_payload(run), "accepted": False}
        if status in {"failed", "waiting_review"} and resume_from is None:
            raise WorkflowStateError(
                "failed or review-paused workflow requires an explicit resume_from guard"
            )
        resume = resume_from is not None
        if mode == "background":
            if resume:
                future = await asyncio.to_thread(
                    self.workflow_engine.submit_resume,
                    run_id,
                    from_step_id=resume_from,
                    project_id=project_id,
                )
            else:
                future = await asyncio.to_thread(
                    self.workflow_engine.submit,
                    run_id,
                    project_id=project_id,
                )
            self._background_futures.add(future)
            future.add_done_callback(self._background_futures.discard)
            current = await asyncio.to_thread(
                self.workflow_engine.get_run,
                run_id,
                project_id=project_id,
            )
            return {"workflow": await self._workflow_payload(current), "accepted": True}
        if resume:
            completed = await asyncio.to_thread(
                _resume_workflow_sync,
                self.workflow_engine,
                run_id,
                resume_from,
                project_id,
            )
        else:
            completed = await asyncio.to_thread(
                self.workflow_engine.run_sync,
                run_id,
                project_id=project_id,
            )
        return {"workflow": await self._workflow_payload(completed), "accepted": False}

    async def yanzhang_get_workflow(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        run = await asyncio.to_thread(
            self.workflow_engine.get_run,
            _required_str(values, "workflow_id"),
            project_id=_required_str(values, "project_id"),
        )
        return {"workflow": await self._workflow_payload(run)}

    async def yanzhang_cancel_workflow(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        run = await asyncio.to_thread(
            self.workflow_engine.request_cancel,
            _required_str(values, "workflow_id"),
            project_id=_required_str(values, "project_id"),
        )
        return {"workflow": await self._workflow_payload(run)}

    async def resume_workflow(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        run_id = _required_str(values, "workflow_id")
        resume_from = _required_str(values, "resume_from")
        run = await asyncio.to_thread(
            _resume_workflow_sync,
            self.workflow_engine,
            run_id,
            resume_from,
            project_id,
        )
        return {"workflow": await self._workflow_payload(run)}

    async def yanzhang_list_assets(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        limit, offset = _page(values)
        assets = await self._all_assets(
            project_id,
            content_type=_optional_str(values, "content_type"),
            status=_optional_str(values, "status"),
        )
        page = assets[offset : offset + limit]
        return {
            "items": [_asset_summary(asset) for asset in page],
            "count": len(page),
            "total": len(assets),
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(page) < len(assets),
        }

    async def yanzhang_get_asset(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        asset = await self._asset(project_id, _required_str(values, "asset_id"))
        revision_number = _optional_integer(values, "revision")
        if revision_number is not None:
            revision = await asyncio.to_thread(self.storage.get_revision, asset.id, revision_number)
            asset = asset.model_copy(
                update={"blocks": revision.blocks, "current_revision": revision.version}
            )
        start = _integer(values, "chunk_offset", default=0)
        size = _integer(values, "chunk_size", default=8_000)
        text = asset.plain_text()
        payload = _model(asset)
        payload.update(
            {
                "content": text[start : start + size],
                "chunk_offset": start,
                "chunk_size": len(text[start : start + size]),
                "has_more": start + size < len(text),
                "total_characters": len(text),
                "next_offset": min(start + size, len(text)),
            }
        )
        selected_revision = await asyncio.to_thread(
            self.storage.get_revision, asset.id, asset.current_revision
        )
        execution = selected_revision.execution
        return {
            "asset": payload,
            "execution": _model(execution) if execution is not None else None,
        }

    async def create_asset(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        brief = await self._brief_for_project(project_id, _required_str(values, "brief_id"))
        knowledge = await self._materials(project_id, brief.knowledge_item_ids)
        requested_live = _boolean(values, "live", default=False)
        decision = self._route(brief.model_profile_id, request_live=requested_live)
        live = self._live_mode(requested_live, decision)
        recipe = _effective_recipe(brief)
        draft = await self.composer.compose(
            brief,
            recipe,
            knowledge,
            live=live,
            title=_optional_str(values, "title") or brief.selected_title,
        )
        asset = await self._create_traced_asset(
            brief=brief,
            blocks=draft.blocks,
            materials=knowledge,
            title=draft.title,
            project_id=project_id,
            note=f"{draft.mode} 生成母稿",
            model_profile_id=decision.profile.id,
            metadata={
                "mode": draft.mode,
                "route": _model(decision),
                "execution": self._execution(live),
            },
        )
        return {
            "asset": _model(asset),
            "generation_mode": draft.mode,
            "resolved_route": _model(decision),
            "execution": self._execution(live),
        }

    async def yanzhang_create_variant(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        source = await self._asset(project_id, _required_str(values, "asset_id"))
        source_revision = _optional_integer(values, "source_revision")
        if source_revision is not None:
            revision = await asyncio.to_thread(
                self.storage.get_revision, source.id, source_revision
            )
            source = source.model_copy(
                update={"blocks": revision.blocks, "current_revision": revision.version}
            )
        target_channel = cast(Channel, _required_str(values, "target_channel"))
        requested_live = _boolean(values, "live", default=False)
        profile_id = _optional_str(values, "model_profile_id")
        decision = self._route(profile_id, request_live=requested_live)
        live = self._live_mode(requested_live, decision)
        draft = await self.composer.create_variant(
            source,
            target_channel=target_channel,
            instruction=_required_str(values, "instruction", default=""),
            live=live,
        )
        original_brief = await asyncio.to_thread(
            self.storage.get_brief, source.brief_id, project_id=project_id
        )
        variant_brief = original_brief.model_copy(
            update={
                "id": _stable_id("brief-variant", source.id, target_channel, draft.title),
                "channel": target_channel,
                "model_profile_id": profile_id or decision.profile.id,
            }
        )
        asset = await asyncio.to_thread(
            self.storage.create_text_asset,
            variant_brief,
            draft.blocks,
            title=draft.title,
            project_id=project_id,
            parent_asset_id=source.id,
            note=f"{draft.mode} 渠道变体",
            model_profile_id=decision.profile.id,
            metadata={
                "source_revision": source.current_revision,
                "route": _model(decision),
                "execution": self._execution(live),
            },
        )
        return {
            "asset": _model(asset),
            "source_asset_id": source.id,
            "generation_mode": draft.mode,
            "resolved_route": _model(decision),
            "execution": self._execution(live),
        }

    async def yanzhang_list_revisions(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        asset = await self._asset(project_id, _required_str(values, "asset_id"))
        limit, offset = _page(values)
        revisions = await self._all_revisions(asset.id)
        page = revisions[offset : offset + limit]
        return {
            "items": [_model(revision) for revision in page],
            "count": len(page),
            "total": len(revisions),
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(page) < len(revisions),
        }

    async def create_revision(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        asset = await self._asset(project_id, _required_str(values, "asset_id"))
        raw_blocks = values.get("blocks")
        blocks = (
            tuple(ContentBlock.model_validate(block) for block in raw_blocks)
            if isinstance(raw_blocks, list)
            else asset.blocks
        )
        revision = await asyncio.to_thread(
            self.storage.save_revision,
            asset.id,
            blocks,
            note=_required_str(values, "note", default="保存修订"),
            model_profile_id=_optional_str(values, "model_profile_id"),
            expected_revision=_optional_integer(values, "expected_revision"),
            title=_optional_str(values, "title"),
            status=_optional_str(values, "status"),
        )
        return {"revision": _model(revision)}

    async def yanzhang_review_asset(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        asset = await self._asset(project_id, _required_str(values, "asset_id"))
        brief = await asyncio.to_thread(
            self.storage.get_brief, asset.brief_id, project_id=project_id
        )
        material_ids = _str_sequence(values, "material_ids") or brief.knowledge_item_ids
        materials = await self._materials(project_id, material_ids)
        evidence = await self._persist_material_evidence(project_id, materials)
        terms = tuple(await asyncio.to_thread(self.storage.list_project_terms, project_id))
        checks = _review_checks(values)
        selected_dimensions = _selected_review_dimensions(checks)
        local_report = await asyncio.to_thread(
            review_asset, asset, brief=brief, evidence=evidence, terms=terms
        )
        profile_id = _optional_str(values, "model_profile_id")
        requested_live = _boolean(values, "live", default=False)
        decision = self._route(
            profile_id,
            request_live=requested_live,
            required_capability="review",
        )
        live = self._live_mode(requested_live, decision)
        model_issues: tuple[_LiveReviewIssue, ...] = ()
        if live:
            model_issues = await self._model_review(
                asset=asset,
                brief=brief,
                evidence=evidence,
                selected_dimensions=selected_dimensions,
            )
        report = _filtered_review(
            local_report,
            selected_dimensions=selected_dimensions,
            model_issues=model_issues,
        )
        return {
            "review": report,
            "checks": list(checks),
            "review_dimensions": list(selected_dimensions),
            "effective_mode": "live" if live else "local",
            "execution": self._execution(live),
            "requested_model_profile_id": profile_id,
            "resolved_route": _model(decision),
            "model_issue_count": len(model_issues),
        }

    async def _model_review(
        self,
        *,
        asset: TextAsset,
        brief: WritingBrief,
        evidence: tuple[Evidence, ...],
        selected_dimensions: tuple[ReviewDimension, ...],
    ) -> tuple[_LiveReviewIssue, ...]:
        """Run one closed, provider-neutral model pass after local review."""

        system_prompt = (
            "你是砚章审校引擎。仅输出一个JSON对象，不得输出Markdown。"
            "对象必须且只能包含issues；issues每项必须且只能包含dimension、severity、"
            "block_id、message、suggestion。dimension只能来自给定维度，severity只能是"
            "info、warning或error。block_id必须来自给定内容块，也可为null。"
            "事实判断只能依据给定证据；依据不足时只提示人工核对，不得补造事实。"
        )
        user_prompt = json.dumps(
            {
                "task": "review_asset",
                "dimensions": list(selected_dimensions),
                "brief": brief.model_dump(mode="json"),
                "asset": {
                    "id": asset.id,
                    "title": asset.title,
                    "channel": asset.channel,
                    "blocks": [block.model_dump(mode="json") for block in asset.blocks],
                },
                "evidence": [item.model_dump(mode="json") for item in evidence],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        raw = await self.composer.invoke_model(system_prompt, user_prompt)
        try:
            parsed = _LiveReviewPayload.model_validate_json(raw)
        except ValidationError as exc:
            raise ValueError("模型审校结果不符合约定结构") from exc
        allowed_blocks = {block.id for block in asset.blocks}
        selected = set(selected_dimensions)
        for issue in parsed.issues:
            if issue.dimension not in selected:
                raise ValueError("模型审校结果包含未请求的检查维度")
            if issue.block_id is not None and issue.block_id not in allowed_blocks:
                raise ValueError("模型审校结果引用了不存在的内容块")
        return parsed.issues

    async def yanzhang_export_asset(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        export_format = _export_format(_required_str(values, "format", default="docx"))
        template_id = _optional_str(values, "template_id")
        if template_id is not None and export_format != "docx":
            raise ValueError("template_id 仅适用于 DOCX 导出")
        if template_id not in {None, "standard", "brief"}:
            raise ValueError("template_id 应为 standard 或 brief")
        return await self._export_asset(
            project_id=_required_str(values, "project_id"),
            asset_id=_required_str(values, "asset_id"),
            export_format=export_format,
            revision=_optional_integer(values, "revision"),
            template_id=template_id,
            filename=_optional_str(values, "filename"),
            creator="yanzhang_export_asset",
        )

    async def import_document(self, request: RequestInput) -> PlatformResult:
        """Decode, parse and optionally persist an uploaded document as material."""

        values = _payload(request)
        encoded = _required_str(values, "data_base64")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("data_base64 不是有效的 Base64 内容") from exc
        filename = _required_str(values, "filename")
        parsed = await asyncio.to_thread(
            parse_document,
            data,
            filename=filename,
            media_type=_optional_str(values, "media_type"),
        )
        result: PlatformResult = {"document": _dataclass(parsed)}
        project_id = _optional_str(values, "project_id")
        if project_id is not None:
            await self._project(project_id)
            item = KnowledgeItem.model_validate(
                {
                    "project_id": project_id,
                    "title": parsed.title,
                    "content": parsed.text,
                    "kind": _required_str(values, "kind", default="source"),
                    "tags": _str_sequence(values, "tags"),
                }
            )
            saved = await asyncio.to_thread(self.knowledge.upsert_item, item)
            result["material"] = _model(saved)
        return result

    async def yanzhang_search_literature(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        provider = _required_str(values, "provider", default="crossref")
        records = await self.academic.search_metadata(
            provider,
            _required_str(values, "query"),
            limit=_integer(values, "limit", default=10),
        )
        saved = await asyncio.to_thread(
            self.academic_repository.upsert_records, project_id, records
        )
        return {
            "items": [_model(record) for record in saved],
            "count": len(saved),
            "provider": provider,
        }

    async def yanzhang_import_literature(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        bibliography_format = cast(
            Literal["bibtex", "ris", "csl-json"], _required_str(values, "format")
        )
        records = await asyncio.to_thread(
            self.academic.import_records,
            _required_str(values, "content"),
            bibliography_format,
        )
        tags = _str_sequence(values, "tags")
        if tags:
            tagged_records: list[BibliographicRecord] = []
            for record in records:
                keywords = list(dict.fromkeys([*record.keywords, *tags]))
                if len(keywords) > 100:
                    raise ValueError("文献关键词与导入标签合计最多 100 项")
                tagged_records.append(record.model_copy(update={"keywords": keywords}))
            records = tagged_records
        saved = await asyncio.to_thread(
            self.academic_repository.upsert_records, project_id, records
        )
        return {"items": [_model(record) for record in saved], "count": len(saved)}

    async def yanzhang_get_literature(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        record = await asyncio.to_thread(
            self.academic_repository.get_record,
            project_id,
            _required_str(values, "record_id"),
        )
        payload = _model(record)
        if not _boolean(values, "include_abstract", default=True):
            payload["abstract"] = ""
        return {"record": payload}

    async def yanzhang_list_literature(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        limit, offset = _page(values)
        query = _optional_str(values, "query")
        records = await asyncio.to_thread(
            self.academic_repository.list_records,
            project_id,
            query=query,
            limit=limit,
            offset=offset,
        )
        total = await asyncio.to_thread(
            self.academic_repository.count_records,
            project_id,
            query=query,
        )
        items = [_model(record) for record in records]
        if not _boolean(values, "include_abstract", default=False):
            for item in items:
                item["abstract"] = ""
        return _academic_page(items, total=total, limit=limit, offset=offset)

    async def yanzhang_list_evidence(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        limit, offset = _page(values)
        record_id = _optional_str(values, "record_id")
        evidence = await asyncio.to_thread(
            self.academic_repository.list_evidence,
            project_id,
            record_id=record_id,
            limit=limit,
            offset=offset,
        )
        total = await asyncio.to_thread(
            self.academic_repository.count_evidence,
            project_id,
            record_id=record_id,
        )
        return _academic_page(
            [_model(item) for item in evidence],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def yanzhang_get_evidence(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        evidence = await asyncio.to_thread(
            self.academic_repository.get_evidence,
            _required_str(values, "project_id"),
            _required_str(values, "evidence_id"),
        )
        return {"evidence": _model(evidence)}

    async def yanzhang_extract_evidence(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        record = await asyncio.to_thread(
            self.academic_repository.get_record,
            project_id,
            _required_str(values, "record_id"),
        )
        evidence = await asyncio.to_thread(
            self.academic.extract_evidence,
            record,
            _required_str(values, "text"),
            query=_required_str(values, "query", default=""),
            max_snippets=_integer(values, "max_snippets", default=20),
        )
        saved = await asyncio.to_thread(
            self.academic_repository.upsert_evidence_batch,
            project_id,
            evidence,
        )
        return {"items": [_model(item) for item in saved], "count": len(saved)}

    async def yanzhang_build_literature_matrix(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        records = await asyncio.to_thread(
            self.academic_repository.get_records,
            project_id,
            _str_sequence(values, "record_ids"),
        )
        evidence_ids = _str_sequence(values, "evidence_ids")
        evidence = (
            await asyncio.to_thread(
                self.academic_repository.get_evidence_batch,
                project_id,
                evidence_ids,
            )
            if evidence_ids
            else []
        )
        matrix = await asyncio.to_thread(
            self.academic.build_matrix,
            records,
            evidence,
            query=_required_str(values, "query", default=""),
        )
        saved = await asyncio.to_thread(self.academic_repository.upsert_matrix, project_id, matrix)
        return {"matrix": _model(saved)}

    async def yanzhang_list_literature_matrices(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        limit, offset = _page(values)
        matrices = await asyncio.to_thread(
            self.academic_repository.list_matrices,
            project_id,
            limit=limit,
            offset=offset,
        )
        total = await asyncio.to_thread(self.academic_repository.count_matrices, project_id)
        return _academic_page(
            [_model(matrix) for matrix in matrices],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def yanzhang_get_literature_matrix(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        matrix = await asyncio.to_thread(
            self.academic_repository.get_matrix,
            _required_str(values, "project_id"),
            _required_str(values, "matrix_id"),
        )
        return {"matrix": _model(matrix)}

    async def yanzhang_list_research_claims(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        limit, offset = _page(values)
        claims = await asyncio.to_thread(
            self.academic_repository.list_claims,
            project_id,
            limit=limit,
            offset=offset,
        )
        total = await asyncio.to_thread(self.academic_repository.count_claims, project_id)
        return _academic_page(
            [_model(claim) for claim in claims],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def yanzhang_get_research_claim(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        claim = await asyncio.to_thread(
            self.academic_repository.get_claim,
            _required_str(values, "project_id"),
            _required_str(values, "claim_id"),
        )
        return {"claim": _model(claim)}

    async def yanzhang_list_citation_links(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        limit, offset = _page(values)
        claim_id = _optional_str(values, "claim_id")
        record_id = _optional_str(values, "record_id")
        evidence_id = _optional_str(values, "evidence_id")
        links = await asyncio.to_thread(
            self.academic_repository.list_links,
            project_id,
            claim_id=claim_id,
            record_id=record_id,
            evidence_id=evidence_id,
            limit=limit,
            offset=offset,
        )
        total = await asyncio.to_thread(
            self.academic_repository.count_links,
            project_id,
            claim_id=claim_id,
            record_id=record_id,
            evidence_id=evidence_id,
        )
        return _academic_page(
            [_model(link) for link in links],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def yanzhang_get_citation_link(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        link = await asyncio.to_thread(
            self.academic_repository.get_link,
            _required_str(values, "project_id"),
            _required_str(values, "link_id"),
        )
        return {"link": _model(link)}

    async def yanzhang_verify_citations(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        records = await asyncio.to_thread(
            self.academic_repository.get_records,
            project_id,
            _str_sequence(values, "record_ids"),
        )
        evidence = await asyncio.to_thread(
            self.academic_repository.get_evidence_batch,
            project_id,
            _str_sequence(values, "evidence_ids"),
        )
        claims = _academic_models(values, "claims", ResearchClaim)
        links = _academic_models(values, "links", ClaimCitationLink)
        audit = await asyncio.to_thread(
            self.academic.verify_citations, records, evidence, claims, links
        )
        await asyncio.to_thread(
            self.academic_repository.replace_claim_set,
            project_id,
            claims,
            audit.links,
        )
        return {"citation_audit": _model(audit)}

    async def yanzhang_format_bibliography(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        records = await asyncio.to_thread(
            self.academic_repository.get_records,
            project_id,
            _str_sequence(values, "record_ids"),
        )
        style = cast(
            Literal["gb-t-7714", "apa", "mla", "chicago"],
            _required_str(values, "style", default="gb-t-7714"),
        )
        bibliography = await asyncio.to_thread(self.academic.format_bibliography, records, style)
        return {"items": bibliography, "count": len(bibliography), "style": style}

    async def yanzhang_suggest_academic_titles(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        record_ids = _str_sequence(values, "record_ids")
        records = (
            await asyncio.to_thread(self.academic_repository.get_records, project_id, record_ids)
            if record_ids
            else []
        )
        count = _integer(values, "count", default=5)
        suggestions = await asyncio.to_thread(
            self.academic.suggest_titles,
            _research_brief(values),
            records,
            count=count,
        )
        return {
            "items": [_model(item) for item in suggestions],
            "count": len(suggestions),
            "requested_count": count,
            "execution": self._execution(False),
        }

    async def yanzhang_create_academic_outline(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        record_ids = _str_sequence(values, "record_ids")
        evidence_ids = _str_sequence(values, "evidence_ids")
        records = (
            await asyncio.to_thread(self.academic_repository.get_records, project_id, record_ids)
            if record_ids
            else []
        )
        evidence = (
            await asyncio.to_thread(
                self.academic_repository.get_evidence_batch, project_id, evidence_ids
            )
            if evidence_ids
            else []
        )
        outline = await asyncio.to_thread(
            self.academic.create_outline,
            _research_brief(values),
            records,
            evidence,
        )
        return {"outline": _model(outline), "execution": self._execution(False)}

    async def yanzhang_draft_abstract(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        record_ids = _str_sequence(values, "record_ids")
        records = (
            await asyncio.to_thread(self.academic_repository.get_records, project_id, record_ids)
            if record_ids
            else []
        )
        claims = _academic_models(values, "claims", ResearchClaim)
        links = _academic_models(values, "links", ClaimCitationLink)
        max_characters = _integer(values, "max_characters", default=800)
        journal = JournalProfile(name="本次摘要长度规则", abstract_max_characters=max_characters)
        abstract = await asyncio.to_thread(
            self.academic.draft_abstract,
            _research_brief(values),
            claims,
            links,
            records,
            journal=journal,
        )
        return {"abstract": _model(abstract), "execution": self._execution(False)}

    async def yanzhang_review_academic_integrity(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        project_id = _required_str(values, "project_id")
        await self._project(project_id)
        manuscript = _required_str(values, "manuscript")
        record_ids = _str_sequence(values, "record_ids")
        evidence_ids = _str_sequence(values, "evidence_ids")
        records = (
            await asyncio.to_thread(self.academic_repository.get_records, project_id, record_ids)
            if record_ids
            else []
        )
        evidence = (
            await asyncio.to_thread(
                self.academic_repository.get_evidence_batch, project_id, evidence_ids
            )
            if evidence_ids
            else []
        )
        claims = _academic_models(values, "claims", ResearchClaim)
        links = _academic_models(values, "links", ClaimCitationLink)
        raw_journal = values.get("journal")
        journal = JournalProfile.model_validate(raw_journal) if raw_journal is not None else None
        review = await asyncio.to_thread(
            self.academic.review_integrity,
            records,
            evidence,
            claims,
            links,
            manuscript=manuscript,
            journal=journal,
        )
        return {
            "integrity_review": _model(review),
            "execution": self._execution(False),
            "manuscript_characters": len(manuscript),
            "manuscript_words": manuscript_word_count(manuscript),
            "journal_profile_id": journal.id if journal is not None else None,
        }

    async def yanzhang_prepare_rebuttal(self, request: RequestInput) -> PlatformResult:
        values = _payload(request)
        await self._project(_required_str(values, "project_id"))
        comments = _academic_models(values, "comments", ReviewComment)
        raw_changes = values.get("changes", {})
        if not isinstance(raw_changes, Mapping):
            raise ValueError("changes 应为对象")
        changes = {str(key): _plain_str(value, "changes") for key, value in raw_changes.items()}
        items = await asyncio.to_thread(self.academic.prepare_rebuttal, comments, changes)
        return {
            "items": [_model(item) for item in items],
            "count": len(items),
            "execution": self._execution(False),
        }

    async def _project(self, project_id: str) -> WritingProject:
        return await asyncio.to_thread(self.storage.get_project, project_id)

    async def _material(self, project_id: str, material_id: str) -> KnowledgeItem:
        await self._project(project_id)
        return await asyncio.to_thread(self.knowledge.get_item, material_id, project_id=project_id)

    async def _materials(
        self, project_id: str, material_ids: Sequence[str]
    ) -> tuple[KnowledgeItem, ...]:
        return tuple(
            [await self._material(project_id, material_id) for material_id in material_ids]
        )

    async def _persist_material_evidence(
        self,
        project_id: str,
        materials: Sequence[KnowledgeItem],
    ) -> tuple[Evidence, ...]:
        evidence = tuple(evidence_from_material(item) for item in _fact_materials(materials))
        for item in evidence:
            await asyncio.to_thread(self.knowledge.add_evidence, item, project_id=project_id)
        return evidence

    async def _create_traced_asset(
        self,
        *,
        brief: WritingBrief,
        blocks: Sequence[ContentBlock],
        materials: Sequence[KnowledgeItem],
        title: str,
        project_id: str,
        note: str,
        model_profile_id: str | None,
        metadata: Mapping[str, object],
    ) -> TextAsset:
        fact_materials = _fact_materials(materials)
        linked_blocks, _ = attach_material_evidence(
            blocks,
            fact_materials,
            structural_topic=brief.title,
        )
        await self._persist_material_evidence(project_id, fact_materials)
        asset = await asyncio.to_thread(
            self.storage.create_text_asset,
            brief,
            linked_blocks,
            title=title,
            project_id=project_id,
            note=note,
            model_profile_id=model_profile_id,
            metadata=metadata,
        )
        graph = build_provenance_graph(
            asset,
            fact_materials,
            structural_topic=brief.title,
        )
        await asyncio.to_thread(_persist_provenance_graph, self.knowledge, graph, project_id)
        return asset

    async def _asset_evidence(
        self,
        project_id: str,
        asset: TextAsset,
    ) -> tuple[Evidence, ...]:
        evidence_ids = tuple(
            dict.fromkeys(
                evidence_id for block in asset.blocks for evidence_id in block.evidence_ids
            )
        )
        return tuple(
            [
                await asyncio.to_thread(
                    self.knowledge.get_evidence,
                    evidence_id,
                    project_id=project_id,
                )
                for evidence_id in evidence_ids
            ]
        )

    async def _validate_material_ids(self, project_id: str, material_ids: Sequence[str]) -> None:
        await self._materials(project_id, material_ids)

    async def _asset(self, project_id: str, asset_id: str) -> TextAsset:
        await self._project(project_id)
        return await asyncio.to_thread(self.storage.get_text_asset, asset_id, project_id=project_id)

    async def _all_projects(self) -> list[WritingProject]:
        projects: list[WritingProject] = []
        offset = 0
        while True:
            page = await asyncio.to_thread(
                self.storage.list_projects,
                limit=100,
                offset=offset,
            )
            projects.extend(page)
            if len(page) < 100:
                return projects
            offset += len(page)

    async def _all_materials(
        self, project_id: str, *, kind: str | None = None
    ) -> list[KnowledgeItem]:
        items: list[KnowledgeItem] = []
        offset = 0
        while True:
            page = await asyncio.to_thread(
                self.knowledge.list_items,
                project_id=project_id,
                kind=kind,
                limit=100,
                offset=offset,
            )
            items.extend(page)
            if len(page) < 100:
                return items
            offset += len(page)

    async def _all_material_matches(
        self, project_id: str, query: str
    ) -> list[KnowledgeSearchResult]:
        matches: list[KnowledgeSearchResult] = []
        offset = 0
        while True:
            page = await asyncio.to_thread(
                self.knowledge.search,
                query,
                project_id=project_id,
                limit=100,
                offset=offset,
            )
            matches.extend(page)
            if len(page) < 100:
                return matches
            offset += len(page)

    async def _all_assets(
        self,
        project_id: str,
        *,
        content_type: str | None = None,
        status: str | None = None,
    ) -> list[TextAsset]:
        assets: list[TextAsset] = []
        offset = 0
        while True:
            page = await asyncio.to_thread(
                self.storage.list_text_assets,
                project_id=project_id,
                content_type=content_type,
                status=status,
                limit=100,
                offset=offset,
            )
            assets.extend(page)
            if len(page) < 100:
                return assets
            offset += len(page)

    async def _all_revisions(self, asset_id: str) -> list[Revision]:
        revisions: list[Revision] = []
        offset = 0
        while True:
            page = await asyncio.to_thread(
                self.storage.list_revisions,
                asset_id,
                limit=100,
                offset=offset,
            )
            revisions.extend(page)
            if len(page) < 100:
                return revisions
            offset += len(page)

    async def _all_academic_records(
        self, project_id: str, *, query: str | None = None
    ) -> list[BibliographicRecord]:
        records: list[BibliographicRecord] = []
        offset = 0
        while True:
            page = await asyncio.to_thread(
                self.academic_repository.list_records,
                project_id,
                query=query,
                limit=100,
                offset=offset,
            )
            records.extend(page)
            if len(page) < 100:
                return records
            offset += len(page)

    async def _brief_for_project(self, project_id: str, brief_id: str) -> WritingBrief:
        await self._project(project_id)
        return await asyncio.to_thread(self.storage.get_brief, brief_id, project_id=project_id)

    def _brief(self, values: Mapping[str, object]) -> WritingBrief:
        pack_id = _required_str(values, "scenario_pack_id")
        recipe_id = _required_str(values, "recipe_id")
        recipe = get_recipe(recipe_id, pack_id=pack_id)
        channel = _required_str(values, "channel", default="document")
        if channel not in recipe.channels:
            raise ValueError("所选配方不支持指定输出渠道")
        # The executable recipe is the canonical output type.  Accepting an older
        # client-provided label remains backwards compatible, while preventing a
        # brief/asset from claiming a type that its selected recipe does not create.
        _required_str(values, "content_type", default=recipe.content_type)
        content_type = recipe.content_type
        title = _optional_str(values, "topic") or _required_str(values, "title")
        payload: dict[str, object] = {
            "title": title,
            "goal": _required_str(values, "goal"),
            "audience": _required_str(values, "audience"),
            "channel": channel,
            "content_type": content_type,
            "scenario_pack_id": pack_id,
            "recipe_id": recipe_id,
            "tone": _required_str(values, "tone", default="准确、清晰、得体"),
            "length": _required_str(values, "length", default="standard"),
            "target_language": _required_str(values, "target_language", default="zh-CN"),
            "constraints": _str_sequence(values, "constraints"),
            "keywords": _str_sequence(values, "keywords"),
            "knowledge_item_ids": _str_sequence(
                values, "material_ids", fallback="knowledge_item_ids"
            ),
            "model_profile_id": _optional_str(values, "model_profile_id"),
            "selected_title": _optional_str(values, "selected_title"),
            "structure_override": values.get("structure_override", ()),
        }
        brief_id = _optional_str(values, "brief_id") or _optional_str(values, "id")
        if brief_id is not None:
            payload["id"] = brief_id
        return WritingBrief.model_validate(payload)

    def _execution(self, live: bool) -> dict[str, object]:
        """Report the execution engine, never a synthetic routing-profile model."""

        if not live:
            return {
                "mode": "local",
                "engine": "deterministic",
                "provider": None,
                "model": None,
                "label": "本地规则引擎（未调用大模型）",
                "uses_model": False,
            }
        provider = self.runtime.server_provider if self.runtime is not None else None
        return {
            "mode": "live",
            "engine": "language_model",
            "provider": provider.name if provider is not None else None,
            "model": provider.model if provider is not None else None,
            "label": (
                f"{provider.name} · {provider.model}"
                if provider is not None
                else "已注入模型回调（型号未声明）"
            ),
            "uses_model": True,
        }

    def _route(
        self,
        profile_id: str | None,
        *,
        request_live: bool,
        required_capability: str = "drafting",
    ) -> RoutingDecision:
        preset = self.routing_preset if request_live else "local_only"
        decision = route_model(
            ModelRouteRequest(
                preset=preset,
                preferred_profile_id=profile_id,
                required_capabilities=(required_capability,),
            )
        )
        if request_live and profile_id is not None and decision.profile.id != profile_id:
            raise ValueError("指定模型画像不适用于当前路由策略或任务能力")
        return decision

    def _live_mode(self, requested: bool, decision: RoutingDecision) -> bool:
        if not requested:
            return False
        if not self.composer.live_available:
            raise ModelExecutionConfigurationError("实时写作模式尚未配置模型回调")
        if not decision.allows_network:
            raise ModelExecutionConfigurationError("当前模型路由预设选择了本地确定性路径")
        return True

    async def _workflow_payload(self, run: WorkflowRunRecord) -> dict[str, object]:
        project_id = run["project_id"]
        if project_id is None:
            raise RecordNotFoundError("project-scoped workflow not found")
        steps = await asyncio.to_thread(
            self.workflow_engine.list_step_runs,
            run["id"],
            project_id=project_id,
        )
        payload: dict[str, object] = {**dict(run), "steps": [dict(step) for step in steps]}
        execution = run["input"].get("execution")
        payload["execution"] = dict(execution) if isinstance(execution, Mapping) else None
        raw_brief = run["input"].get("brief")
        if isinstance(raw_brief, Mapping):
            brief_id = raw_brief.get("id")
            if isinstance(brief_id, str) and brief_id:
                payload["brief_id"] = brief_id
        return payload

    async def _workflow_research(self, context: StepContext) -> StepResult:
        brief = WritingBrief.model_validate(context.input["brief"])
        project_id = _workflow_project_id(context)
        materials = await self._materials(project_id, brief.knowledge_item_ids)
        evidence = await self._persist_material_evidence(project_id, materials)
        return StepResult(
            output={
                "material_count": len(materials),
                "evidence_ids": [item.id for item in evidence],
            },
            state_updates={
                "material_ids": [item.id for item in materials],
                "material_count": len(materials),
                "evidence_ids": [item.id for item in evidence],
            },
        )

    async def _workflow_titles(self, context: StepContext) -> StepResult:
        brief = WritingBrief.model_validate(context.input["brief"])
        batch = await asyncio.to_thread(
            generate_candidates, CandidateRequest(brief=brief, kind="title", count=8)
        )
        selected_title = brief.selected_title or batch.recommended
        return StepResult(
            output={
                "candidate_batch": _model(batch),
                "selected_title": selected_title,
                "execution": self._execution(False),
            },
            state_updates={"selected_title": selected_title},
        )

    async def _workflow_outline(self, context: StepContext) -> StepResult:
        brief = WritingBrief.model_validate(context.input["brief"])
        recipe = _effective_recipe(brief)
        outline = [
            {"id": section.id, "title": section.title, "purpose": section.purpose}
            for section in recipe.sections
        ]
        return StepResult(
            output={"outline": outline, "execution": self._execution(False)},
            state_updates={"outline": outline},
        )

    async def _workflow_compose(self, context: StepContext) -> StepResult:
        brief = WritingBrief.model_validate(context.input["brief"])
        project_id = _workflow_project_id(context)
        materials = await self._materials(project_id, brief.knowledge_item_ids)
        recipe = _effective_recipe(brief)
        live = _workflow_boolean(context, "live", default=False)
        title_value = context.state.get("selected_title")
        title = title_value if isinstance(title_value, str) else brief.title
        draft = await self.composer.compose(brief, recipe, materials, live=live, title=title)
        route = context.input.get("resolved_route")
        profile_id = None
        if isinstance(route, Mapping):
            profile = route.get("profile")
            if isinstance(profile, Mapping) and isinstance(profile.get("id"), str):
                profile_id = cast(str, profile["id"])
        asset = await self._create_traced_asset(
            brief=brief,
            blocks=draft.blocks,
            materials=materials,
            title=draft.title,
            project_id=project_id,
            note=f"工作流 {draft.mode} 生成母稿",
            model_profile_id=profile_id,
            metadata={
                "workflow_run_id": context.run_id,
                "mode": draft.mode,
                "execution": self._execution(live),
            },
        )
        return StepResult(
            output={
                "asset": _model(asset),
                "generation_mode": draft.mode,
                "execution": self._execution(live),
            },
            state_updates={"output_asset_id": asset.id, "generation_mode": draft.mode},
        )

    async def _workflow_review(self, context: StepContext) -> StepResult:
        if not _workflow_boolean(context, "auto_review", default=True):
            return StepResult(output={"skipped": True})
        project_id = _workflow_project_id(context)
        asset_id = _workflow_state_string(context, "output_asset_id")
        asset = await self._asset(project_id, asset_id)
        brief = await asyncio.to_thread(
            self.storage.get_brief, asset.brief_id, project_id=project_id
        )
        materials = await self._materials(project_id, brief.knowledge_item_ids)
        evidence = await self._persist_material_evidence(project_id, materials)
        terms = tuple(await asyncio.to_thread(self.storage.list_project_terms, project_id))
        report = await asyncio.to_thread(
            review_asset,
            asset,
            brief=brief,
            evidence=evidence,
            terms=terms,
        )
        return StepResult(
            output={"review": _model(report), "execution": self._execution(False)},
            state_updates={"review_score": report.overall_score, "review_passed": report.passed},
        )

    async def _workflow_export(self, context: StepContext) -> StepResult:
        raw_formats = context.input.get("requested_exports", [])
        if not isinstance(raw_formats, list):
            raise ValueError("requested_exports 应为列表")
        project_id = _workflow_project_id(context)
        asset_id = _workflow_state_string(context, "output_asset_id")
        exports: list[dict[str, object]] = []
        for raw_format in raw_formats:
            export_format = _export_format(_plain_str(raw_format, "requested_exports"))
            result = await self._export_asset(
                project_id=project_id,
                asset_id=asset_id,
                export_format=export_format,
                revision=None,
                template_id=None,
                filename=None,
                creator="yanzhang_create_workflow",
            )
            exports.append(cast(dict[str, object], result["artifact"]))
        return StepResult(output={"exports": exports}, state_updates={"exports": exports})

    async def _export_asset(
        self,
        *,
        project_id: str,
        asset_id: str,
        export_format: ExportFormat,
        revision: int | None,
        template_id: str | None,
        filename: str | None,
        creator: str,
    ) -> PlatformResult:
        asset = await self._asset(project_id, asset_id)
        selected_revision = revision or asset.current_revision
        snapshot = await asyncio.to_thread(
            self.storage.get_revision,
            asset.id,
            selected_revision,
        )
        asset = asset.model_copy(
            update={"blocks": snapshot.blocks, "current_revision": snapshot.version}
        )
        evidence = await self._asset_evidence(project_id, asset)
        payload = await asyncio.to_thread(
            _render_export,
            asset,
            export_format,
            evidence,
            template_id,
        )
        desired = unique_filename(
            filename or asset.title,
            suffix=_SUFFIXES[export_format],
        )
        metadata = await asyncio.to_thread(
            self.artifact_store.put,
            payload,
            filename=desired,
            mime=_MIME_TYPES[export_format],
            project_id=project_id,
            asset_id=asset.id,
            revision_id=snapshot.id,
            creator=creator,
        )
        artifact = _object(metadata)
        return {
            **artifact,
            "artifact": artifact,
            "asset_id": asset.id,
            "revision": asset.current_revision,
            "format": export_format,
            "template_id": template_id or ("standard" if export_format == "docx" else None),
        }


def _payload(request: RequestInput) -> dict[str, object]:
    if isinstance(request, BaseModel):
        return cast(dict[str, object], request.model_dump(mode="python"))
    if not isinstance(request, Mapping):
        raise TypeError("request 应为对象")
    return {str(key): value for key, value in request.items()}


def _required_str(values: Mapping[str, object], key: str, *, default: str | None = None) -> str:
    value = values.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} 应为字符串")
    normalized = value.strip()
    if not normalized and default is None:
        raise ValueError(f"{key} 不得为空")
    return normalized


def _optional_str(values: Mapping[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} 应为字符串")
    normalized = value.strip()
    return normalized or None


def _plain_str(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} 应为字符串")
    return value


def _integer(values: Mapping[str, object], key: str, *, default: int) -> int:
    value = values.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} 应为整数")
    return value


def _optional_integer(values: Mapping[str, object], key: str) -> int | None:
    value = values.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} 应为整数")
    return value


def _boolean(values: Mapping[str, object], key: str, *, default: bool) -> bool:
    value = values.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} 应为布尔值")
    return value


def _str_sequence(
    values: Mapping[str, object], key: str, *, fallback: str | None = None
) -> tuple[str, ...]:
    value = values.get(key)
    if value is None and fallback is not None:
        value = values.get(fallback)
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{key} 应为字符串列表")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{key} 不得包含空值")
        normalized.append(item.strip())
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{key} 不得重复")
    return tuple(normalized)


def _review_checks(values: Mapping[str, object]) -> tuple[str, ...]:
    checks = _str_sequence(values, "checks") or (
        "structure",
        "style",
        "facts",
        "citations",
    )
    unknown = tuple(check for check in checks if check not in _REVIEW_CHECK_DIMENSIONS)
    if unknown:
        raise ValueError("checks 包含不支持的审校项")
    return checks


def _selected_review_dimensions(checks: tuple[str, ...]) -> tuple[ReviewDimension, ...]:
    selected = {dimension for check in checks for dimension in _REVIEW_CHECK_DIMENSIONS[check]}
    return tuple(dimension for dimension in _REVIEW_DIMENSIONS if dimension in selected)


def _filtered_review(
    report: ReviewReport,
    *,
    selected_dimensions: tuple[ReviewDimension, ...],
    model_issues: tuple[_LiveReviewIssue, ...],
) -> dict[str, object]:
    selected = set(selected_dimensions)
    issues = [
        cast(dict[str, object], issue.model_dump(mode="json"))
        for issue in report.issues
        if issue.dimension in selected
    ]
    known = {
        (
            cast(str, issue["dimension"]),
            cast(str | None, issue.get("block_id")),
            cast(str, issue["message"]),
        )
        for issue in issues
    }
    for index, model_issue in enumerate(model_issues, 1):
        item = cast(dict[str, object], model_issue.model_dump(mode="json"))
        identity = (model_issue.dimension, model_issue.block_id, model_issue.message)
        if identity in known:
            continue
        item["id"] = f"model-issue-{index:03d}"
        issues.append(item)
        known.add(identity)

    dimensions: list[dict[str, object]] = []
    for local in report.dimensions:
        if local.dimension not in selected:
            continue
        matching = [item for item in issues if item["dimension"] == local.dimension]
        penalty = sum(
            _REVIEW_PENALTIES[cast(ReviewSeverity, item["severity"])] for item in matching
        )
        dimensions.append(
            {
                "dimension": local.dimension,
                "label": local.label,
                "score": max(0, 100 - penalty),
                "issue_count": len(matching),
                "summary": (
                    "检查通过，未发现规则级问题。"
                    if not matching
                    else f"发现 {len(matching)} 项可处理问题。"
                ),
            }
        )
    overall_score = round(sum(cast(int, item["score"]) for item in dimensions) / len(dimensions))
    return {
        "asset_id": report.asset_id,
        "overall_score": overall_score,
        "passed": overall_score >= 80 and all(item["severity"] != "error" for item in issues),
        "dimensions": dimensions,
        "issues": issues,
        "metrics": report.metrics.model_dump(mode="json"),
    }


def _page(values: Mapping[str, object]) -> tuple[int, int]:
    limit = _integer(values, "limit", default=20)
    offset = _integer(values, "offset", default=0)
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("分页参数超出范围")
    return limit, offset


def _academic_page(
    items: list[dict[str, object]],
    *,
    total: int,
    limit: int,
    offset: int,
) -> PlatformResult:
    """Build the stable resumable collection envelope used by academic APIs."""

    return {
        "items": items,
        "count": len(items),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


def _model(value: BaseModel) -> dict[str, object]:
    return cast(dict[str, object], value.model_dump(mode="json"))


def _object(value: object) -> dict[str, object]:
    if isinstance(value, BaseModel):
        return _model(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        raw = asdict(value)
        return {str(key): _json_safe(item) for key, item in raw.items()}
    raise TypeError("artifact writer 返回值应为对象")


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _dataclass(value: object) -> dict[str, object]:
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("value 应为 dataclass 实例")
    # ParsedDocument contains a read-only mapping, so copy its public fields
    # explicitly instead of deep-copying MappingProxyType through asdict().
    title = getattr(value, "title", None)
    content_type = getattr(value, "content_type", None)
    blocks = getattr(value, "blocks", None)
    metadata = getattr(value, "metadata", None)
    warnings = getattr(value, "warnings", None)
    text = getattr(value, "text", None)
    if not isinstance(title, str) or not isinstance(content_type, str):
        raise TypeError("parsed document 字段无效")
    if not isinstance(blocks, tuple) or not isinstance(metadata, Mapping):
        raise TypeError("parsed document 字段无效")
    return {
        "title": title,
        "content_type": content_type,
        "blocks": [_json_safe(block) for block in blocks],
        "metadata": {str(key): _json_safe(item) for key, item in metadata.items()},
        "warnings": list(warnings) if isinstance(warnings, tuple) else [],
        "text": text if isinstance(text, str) else "",
    }


def _material_summary(item: KnowledgeItem) -> dict[str, object]:
    payload = _model(item)
    payload.pop("content", None)
    payload["character_count"] = len(item.content)
    payload["preview"] = item.content[:500]
    return payload


def _asset_summary(asset: TextAsset) -> dict[str, object]:
    payload = _model(asset)
    payload.pop("blocks", None)
    payload["character_count"] = len(asset.plain_text())
    payload["preview"] = asset.plain_text()[:500]
    return payload


def _excerpt(content: str, query: str, *, size: int = 500) -> str:
    position = content.casefold().find(query.casefold())
    if position < 0:
        return content[:size]
    start = max(0, position - size // 3)
    return content[start : start + size]


def _persist_provenance_graph(
    repository: KnowledgeRepository,
    graph: ProvenanceGraph,
    project_id: str,
) -> None:
    for evidence in graph.evidence:
        repository.add_evidence(evidence, project_id=project_id)
    for claim in graph.claims:
        repository.save_claim(claim, project_id=project_id)
    for citation in graph.citations:
        repository.save_citation(citation, project_id=project_id)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _effective_recipe(brief: WritingBrief) -> RecipeDefinition:
    """Return the selected recipe with an explicitly saved section plan applied."""

    recipe = get_recipe(brief.recipe_id, pack_id=brief.scenario_pack_id)
    if not brief.structure_override:
        return recipe
    sections = tuple(
        RecipeSection(
            id=section.id,
            title=section.title,
            purpose=section.purpose,
            required=section.required,
        )
        for section in brief.structure_override
    )
    return recipe.model_copy(update={"sections": sections})


def _fact_materials(materials: Sequence[KnowledgeItem]) -> tuple[KnowledgeItem, ...]:
    """Exclude writing-style references from the factual evidence boundary."""

    return tuple(item for item in materials if item.kind != "style_reference")


def _academic_models[ModelT: BaseModel](
    values: Mapping[str, object], key: str, model_type: type[ModelT]
) -> list[ModelT]:
    raw = values.get(key, [])
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{key} 应为对象列表")
    return [model_type.model_validate(item) for item in raw]


def _research_brief(values: Mapping[str, object]) -> ResearchBrief:
    return ResearchBrief.model_validate(
        {
            "title": _required_str(values, "title"),
            "research_question": _required_str(values, "research_question"),
            "discipline": _required_str(values, "discipline", default=""),
            "purpose": _required_str(values, "purpose", default=""),
            "audience": _required_str(values, "audience", default="学术读者"),
            "document_type": _required_str(values, "document_type", default="研究论文"),
            "language": _required_str(values, "language", default="zh-CN"),
            "keywords": list(_str_sequence(values, "keywords")),
            "constraints": list(_str_sequence(values, "constraints")),
            "method_notes": _required_str(values, "method_notes", default=""),
        }
    )


def _workflow_project_id(context: StepContext) -> str:
    value = context.input.get("project_id")
    if not isinstance(value, str) or not value:
        raise ValueError("工作流缺少 project_id")
    return value


def _workflow_state_string(context: StepContext, key: str) -> str:
    value = context.state.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"工作流状态缺少 {key}")
    return value


def _workflow_boolean(context: StepContext, key: str, *, default: bool) -> bool:
    value = context.input.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"工作流输入 {key} 应为布尔值")
    return value


def _resume_workflow_sync(
    engine: WorkflowEngine,
    run_id: str,
    from_step_id: str | None = None,
    project_id: str | None = None,
) -> WorkflowRunRecord:
    return asyncio.run(
        engine.resume(
            run_id,
            from_step_id=from_step_id,
            project_id=project_id,
        )
    )


def _export_format(value: str) -> ExportFormat:
    aliases = {"md": "markdown", "txt": "text", "tex": "latex"}
    normalized = aliases.get(value.casefold(), value.casefold())
    if normalized not in _MIME_TYPES:
        raise ValueError("导出格式应为 DOCX、PDF、Markdown、TXT、HTML、LaTeX 或 CSV")
    return normalized


def _render_export(
    asset: TextAsset,
    export_format: ExportFormat,
    evidence: Sequence[Evidence] = (),
    template_id: str | None = None,
) -> bytes:
    if export_format == "docx":
        return build_docx_from_blocks(
            asset.title,
            asset.blocks,
            template_style=template_id or "standard",
        )
    core_format = cast(
        CoreExportFormat,
        {"text": "txt", "csv": "citation_csv"}.get(export_format, export_format),
    )
    try:
        return export_core_asset(asset, format=core_format, evidence=evidence).data
    except ExportDependencyError:
        if export_format != "pdf":
            raise
        return _render_minimal_pdf(asset)


def _render_markdown(asset: TextAsset) -> str:
    lines = [f"# {asset.title}", ""]
    for block in asset.blocks:
        if block.kind == "heading":
            lines.extend((f"{'#' * (block.heading_level or 1)} {block.text}", ""))
        elif block.kind == "list":
            lines.extend(f"- {line}" for line in block.text.splitlines() if line.strip())
            lines.append("")
        elif block.text:
            lines.extend((block.text, ""))
    return "\n".join(lines).rstrip() + "\n"


def _render_html(asset: TextAsset) -> str:
    body: list[str] = [f"<h1>{html.escape(asset.title)}</h1>"]
    for block in asset.blocks:
        escaped = html.escape(block.text).replace("\n", "<br>\n")
        if block.kind == "heading":
            level = block.heading_level or 1
            body.append(f"<h{level}>{escaped}</h{level}>")
        elif block.kind == "quote":
            body.append(f"<blockquote>{escaped}</blockquote>")
        else:
            body.append(f"<p>{escaped}</p>")
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{html.escape(asset.title)}</title></head><body>" + "".join(body) + "</body></html>"
    )


def _render_latex(asset: TextAsset) -> str:
    lines = [
        r"\documentclass[UTF8]{ctexart}",
        r"\usepackage{longtable}",
        rf"\title{{{_latex_escape(asset.title)}}}",
        r"\begin{document}",
        r"\maketitle",
    ]
    for block in asset.blocks:
        content = _latex_escape(block.text)
        if block.kind == "heading":
            command = "section" if (block.heading_level or 1) <= 1 else "subsection"
            lines.append(rf"\{command}{{{content}}}")
        elif block.text:
            lines.extend((content, ""))
    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def _latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _render_csv(asset: TextAsset) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(("order", "kind", "heading_level", "text"))
    for block in asset.blocks:
        writer.writerow((block.order, block.kind, block.heading_level or "", block.text))
    return stream.getvalue()


def _render_minimal_pdf(asset: TextAsset) -> bytes:
    """Build a bounded PDF fallback when the richer renderer is not installed."""

    summary = f"{asset.title}\n\n{asset.plain_text()}"
    ascii_summary = summary.encode("ascii", "replace").decode("ascii")[:40_000]
    lines = [ascii_summary[index : index + 80] for index in range(0, len(ascii_summary), 80)]
    commands = ["BT /F1 10 Tf 50 790 Td"]
    for index, line in enumerate(lines[:45]):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"{'0 -16 Td ' if index else ''}({escaped}) Tj")
    commands.append("ET")
    content = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, item in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(item)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


__all__ = [
    "ArtifactWriter",
    "ExportFormat",
    "PlatformResult",
    "RequestInput",
    "YanzhangPlatformService",
]
