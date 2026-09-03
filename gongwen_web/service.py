"""Transport-neutral business facade for Gongwen writing operations.

The web application and MCP server share this facade so provider resolution,
demo/live dispatch, worker-thread offloading, and model-usage accounting have a
single implementation.  Network access remains inside the existing provider
adapters reached through :mod:`gongwen_web.live`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from time import perf_counter
from typing import Protocol

from gongwen_web.demo import (
    generate_demo as default_generate_demo,
)
from gongwen_web.demo import (
    review_demo as default_review_demo,
)
from gongwen_web.demo import (
    rewrite_demo as default_rewrite_demo,
)
from gongwen_web.fact_audit import FactAuditResult
from gongwen_web.fact_audit import audit_document as default_fact_audit
from gongwen_web.live import (
    LiveRequestError,
    ProviderProbeResult,
)
from gongwen_web.live import (
    generate_live as default_generate_live,
)
from gongwen_web.live import (
    generate_titles_live as default_generate_titles_live,
)
from gongwen_web.live import (
    probe_provider as default_probe_provider,
)
from gongwen_web.live import (
    review_live as default_review_live,
)
from gongwen_web.live import (
    rewrite_live as default_rewrite_live,
)
from gongwen_web.models import (
    FactAuditRequest,
    GeneratedDocument,
    GenerateRequest,
    GenerationMeta,
    ProviderProbeRequest,
    ProviderSettings,
    ReviewRequest,
    ReviewResult,
    RewriteRequest,
    RewriteResult,
)
from gongwen_web.runtime import RuntimeSettings
from gongwen_web.storage import GongwenStorage
from gongwen_web.title_engine import (
    TitleGenerationRequest,
    TitleGenerationResult,
)
from gongwen_web.title_engine import (
    generate_titles_demo as default_generate_titles_demo,
)
from yanzhang.providers.errors import ProviderError

type GenerateInput = GenerateRequest | Mapping[str, object]
type TitleGenerationInput = TitleGenerationRequest | Mapping[str, object]
type RewriteInput = RewriteRequest | Mapping[str, object]
type ReviewInput = ReviewRequest | Mapping[str, object]
type FactAuditInput = FactAuditRequest | Mapping[str, object]
type ProviderProbeInput = ProviderProbeRequest | Mapping[str, object]

type GenerateDemo = Callable[[GenerateRequest], GeneratedDocument]
type GenerateLive = Callable[[GenerateRequest], Awaitable[GeneratedDocument]]
type GenerateTitlesDemo = Callable[[TitleGenerationRequest], TitleGenerationResult]
type GenerateTitlesLive = Callable[[TitleGenerationRequest], Awaitable[TitleGenerationResult]]
type RewriteDemo = Callable[[RewriteRequest], RewriteResult]
type RewriteLive = Callable[[RewriteRequest], Awaitable[RewriteResult]]
type ReviewDemo = Callable[[ReviewRequest], ReviewResult]
type ReviewLive = Callable[[ReviewRequest], Awaitable[ReviewResult]]
type ProbeProvider = Callable[[ProviderSettings], Awaitable[ProviderProbeResult]]
type Clock = Callable[[], float]


class FactAuditor(Protocol):
    """Callable contract for the deterministic fact-audit engine."""

    def __call__(
        self,
        *,
        content: str,
        materials: str | Sequence[str],
        title: str = "",
    ) -> FactAuditResult: ...


class GongwenService:
    """Coordinate provider-neutral Gongwen writing operations.

    Mapping inputs are the preferred boundary for HTTP and MCP transports.  The
    facade resolves server-owned provider settings before Pydantic validation;
    this is required for live title requests whose closed input model requires a
    provider.  Already-validated model inputs are treated as prepared commands,
    which avoids resolving a server credential twice.
    """

    def __init__(
        self,
        storage: GongwenStorage,
        runtime: RuntimeSettings,
        *,
        generate_demo_fn: GenerateDemo = default_generate_demo,
        generate_live_fn: GenerateLive = default_generate_live,
        generate_titles_demo_fn: GenerateTitlesDemo = default_generate_titles_demo,
        generate_titles_live_fn: GenerateTitlesLive = default_generate_titles_live,
        rewrite_demo_fn: RewriteDemo = default_rewrite_demo,
        rewrite_live_fn: RewriteLive = default_rewrite_live,
        review_demo_fn: ReviewDemo = default_review_demo,
        review_live_fn: ReviewLive = default_review_live,
        fact_audit_fn: FactAuditor = default_fact_audit,
        probe_provider_fn: ProbeProvider = default_probe_provider,
        clock: Clock = perf_counter,
    ) -> None:
        self.storage = storage
        self.runtime = runtime
        self._generate_demo = generate_demo_fn
        self._generate_live = generate_live_fn
        self._generate_titles_demo = generate_titles_demo_fn
        self._generate_titles_live = generate_titles_live_fn
        self._rewrite_demo = rewrite_demo_fn
        self._rewrite_live = rewrite_live_fn
        self._review_demo = review_demo_fn
        self._review_live = review_live_fn
        self._fact_audit = fact_audit_fn
        self._probe_provider = probe_provider_fn
        self._clock = clock

    def resolve_provider_payload(
        self,
        payload: Mapping[str, object],
        *,
        force: bool = False,
    ) -> dict[str, object]:
        """Return a copy with an optional server-owned provider resolved.

        ``force`` is used by the provider probe, which has no separate ``live``
        flag.  The live-value interpretation intentionally matches the original
        web contract.
        """

        prepared = dict(payload)
        raw_live = prepared.get("live")
        live_requested = (
            raw_live is True
            or raw_live == 1
            or (isinstance(raw_live, str) and raw_live.casefold() == "true")
        )
        if not force and not live_requested:
            return prepared

        raw_provider = prepared.get("provider")
        client_provider: ProviderSettings | None = None
        if raw_provider is not None:
            client_provider = ProviderSettings.model_validate(raw_provider)
        resolved = self.runtime.resolve_provider(client_provider)
        if resolved is not None:
            prepared["provider"] = resolved.model_dump(mode="json", exclude_none=True)
        return prepared

    async def generate(self, request: GenerateInput) -> GeneratedDocument:
        """Generate one complete draft through the selected execution mode."""

        command = self._generate_request(request)
        started = self._clock()
        try:
            if command.live:
                result = await self._generate_live(command)
            else:
                result = await asyncio.to_thread(self._generate_demo, command)
        except (LiveRequestError, ProviderError) as exc:
            if command.live:
                await self._record_failure("generate", command.provider, started, exc)
            raise
        await self._record_success("generate", result.meta, started)
        return result

    async def generate_titles(self, request: TitleGenerationInput) -> TitleGenerationResult:
        """Generate and rank title candidates through the selected mode."""

        command = self._title_request(request)
        started = self._clock()
        try:
            if command.live:
                result = await self._generate_titles_live(command)
            else:
                result = await asyncio.to_thread(self._generate_titles_demo, command)
        except (LiveRequestError, ProviderError) as exc:
            if command.live:
                await self._record_failure("titles", command.provider, started, exc)
            raise
        await self._record_success("titles", result.meta, started)
        return result

    async def rewrite(self, request: RewriteInput) -> RewriteResult:
        """Rewrite selected text through the selected execution mode."""

        command = self._rewrite_request(request)
        started = self._clock()
        try:
            if command.live:
                result = await self._rewrite_live(command)
            else:
                result = await asyncio.to_thread(self._rewrite_demo, command)
        except (LiveRequestError, ProviderError) as exc:
            if command.live:
                await self._record_failure("rewrite", command.provider, started, exc)
            raise
        await self._record_success("rewrite", result.meta, started)
        return result

    async def review(self, request: ReviewInput) -> ReviewResult:
        """Review a document through the selected execution mode."""

        command = self._review_request(request)
        started = self._clock()
        try:
            if command.live:
                result = await self._review_live(command)
            else:
                result = await asyncio.to_thread(self._review_demo, command)
        except (LiveRequestError, ProviderError) as exc:
            if command.live:
                await self._record_failure("review", command.provider, started, exc)
            raise
        await self._record_success("review", result.meta, started)
        return result

    async def fact_audit(self, request: FactAuditInput) -> FactAuditResult:
        """Run deterministic fact tracing outside the transport event loop."""

        command = (
            request
            if isinstance(request, FactAuditRequest)
            else FactAuditRequest.model_validate(request)
        )
        return await asyncio.to_thread(
            self._fact_audit,
            title=command.title,
            content=command.content,
            materials=command.materials,
        )

    async def probe_provider(
        self,
        request: ProviderProbeInput | None = None,
    ) -> ProviderProbeResult:
        """Probe a resolved provider and account for the live model request."""

        command = self._probe_request({} if request is None else request)
        started = self._clock()
        try:
            result = await self._probe_provider(command.provider)
        except (LiveRequestError, ProviderError) as exc:
            await self._record_failure("provider_probe", command.provider, started, exc)
            raise
        await self._record_success("provider_probe", result.meta, started)
        return result

    def _generate_request(self, request: GenerateInput) -> GenerateRequest:
        if isinstance(request, GenerateRequest):
            return request
        return GenerateRequest.model_validate(self.resolve_provider_payload(request))

    def _title_request(self, request: TitleGenerationInput) -> TitleGenerationRequest:
        if isinstance(request, TitleGenerationRequest):
            return request
        return TitleGenerationRequest.model_validate(self.resolve_provider_payload(request))

    def _rewrite_request(self, request: RewriteInput) -> RewriteRequest:
        if isinstance(request, RewriteRequest):
            return request
        return RewriteRequest.model_validate(self.resolve_provider_payload(request))

    def _review_request(self, request: ReviewInput) -> ReviewRequest:
        if isinstance(request, ReviewRequest):
            return request
        return ReviewRequest.model_validate(self.resolve_provider_payload(request))

    def _probe_request(self, request: ProviderProbeInput) -> ProviderProbeRequest:
        if isinstance(request, ProviderProbeRequest):
            return request
        return ProviderProbeRequest.model_validate(
            self.resolve_provider_payload(request, force=True)
        )

    async def _record_success(
        self,
        operation: str,
        meta: GenerationMeta,
        started: float,
    ) -> None:
        await asyncio.to_thread(
            self.storage.record_model_usage,
            operation=operation,
            provider=meta.provider or meta.mode,
            model=meta.model or ("deterministic" if meta.mode == "demo" else "unspecified"),
            input_tokens=meta.input_tokens,
            output_tokens=meta.output_tokens,
            total_tokens=meta.total_tokens,
            latency_ms=(self._clock() - started) * 1_000,
            metadata={"mode": meta.mode},
        )

    async def _record_failure(
        self,
        operation: str,
        settings: ProviderSettings | None,
        started: float,
        exc: Exception,
    ) -> None:
        provider = settings.name if settings is not None else None
        model = settings.model if settings is not None else None
        await asyncio.to_thread(
            self.storage.record_model_usage,
            operation=operation,
            provider=str(provider or "live"),
            model=str(model or "unspecified"),
            latency_ms=(self._clock() - started) * 1_000,
            success=False,
            error_code=type(exc).__name__,
            metadata={"mode": "live"},
        )


__all__ = [
    "FactAuditInput",
    "FactAuditor",
    "GenerateInput",
    "GongwenService",
    "ProviderProbeInput",
    "ReviewInput",
    "RewriteInput",
    "TitleGenerationInput",
]
