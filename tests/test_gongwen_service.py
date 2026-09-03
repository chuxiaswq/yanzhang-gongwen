"""Unit tests for the transport-neutral Gongwen business facade."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from pathlib import Path

import pytest

from gongwen_web.demo import generate_demo, review_demo, rewrite_demo
from gongwen_web.fact_audit import FactAuditResult, audit_document
from gongwen_web.live import ProviderProbeResult
from gongwen_web.models import (
    GeneratedDocument,
    GenerateRequest,
    GenerationMeta,
    ProviderSettings,
    ReviewRequest,
    ReviewResult,
    RewriteRequest,
    RewriteResult,
)
from gongwen_web.runtime import RuntimeSettings
from gongwen_web.service import GongwenService
from gongwen_web.storage import GongwenStorage
from gongwen_web.title_engine import (
    TitleGenerationRequest,
    TitleGenerationResult,
    generate_titles_demo,
)
from yanzhang.providers.errors import ProviderTimeoutError


@pytest.mark.asyncio
async def test_demo_engines_and_fact_audit_run_in_worker_threads(tmp_path: Path) -> None:
    loop_thread = threading.get_ident()
    worker_threads: dict[str, int] = {}

    def run_generate(command: GenerateRequest) -> GeneratedDocument:
        worker_threads["generate"] = threading.get_ident()
        return generate_demo(command)

    def run_titles(command: TitleGenerationRequest) -> TitleGenerationResult:
        worker_threads["titles"] = threading.get_ident()
        return generate_titles_demo(command)

    def run_rewrite(command: RewriteRequest) -> RewriteResult:
        worker_threads["rewrite"] = threading.get_ident()
        return rewrite_demo(command)

    def run_review(command: ReviewRequest) -> ReviewResult:
        worker_threads["review"] = threading.get_ident()
        return review_demo(command)

    def run_audit(
        *,
        content: str,
        materials: str | Sequence[str],
        title: str = "",
    ) -> FactAuditResult:
        worker_threads["fact_audit"] = threading.get_ident()
        return audit_document(content=content, materials=materials, title=title)

    storage = GongwenStorage(tmp_path / "service.sqlite3")
    service = GongwenService(
        storage,
        RuntimeSettings(environment="test"),
        generate_demo_fn=run_generate,
        generate_titles_demo_fn=run_titles,
        rewrite_demo_fn=run_rewrite,
        review_demo_fn=run_review,
        fact_audit_fn=run_audit,
    )

    generated = await service.generate({"topic": "基层服务提质"})
    titles = await service.generate_titles({"topic": "基层服务提质"})
    rewritten = await service.rewrite({"text": "扎实做好有关工作。"})
    reviewed = await service.review({"content": "一、总体要求\n扎实推进工作。"})
    audited = await service.fact_audit({"content": "完成10项任务。", "materials": "完成10项任务。"})

    assert generated.meta.mode == "demo"
    assert titles.meta.mode == "demo"
    assert rewritten.meta.mode == "demo"
    assert reviewed.meta.mode == "demo"
    assert audited.metrics.supported_claim_count >= 1
    assert set(worker_threads) == {"generate", "titles", "rewrite", "review", "fact_audit"}
    assert all(thread_id != loop_thread for thread_id in worker_threads.values())

    usage = storage.list_model_usage(limit=10)
    assert {item["operation"] for item in usage} == {
        "generate",
        "titles",
        "rewrite",
        "review",
    }
    assert all(item["provider"] == "demo" for item in usage)
    assert all(item["model"] == "deterministic" for item in usage)
    assert all(item["metadata"] == {"mode": "demo"} for item in usage)


@pytest.mark.asyncio
async def test_model_usage_write_does_not_block_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = GongwenStorage(tmp_path / "nonblocking-usage.sqlite3")
    service = GongwenService(storage, RuntimeSettings(environment="test"))
    write_started = threading.Event()
    release_write = threading.Event()
    original_record = storage.record_model_usage

    def blocking_record(**kwargs: object) -> None:
        write_started.set()
        assert release_write.wait(timeout=2)
        original_record(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(storage, "record_model_usage", blocking_record)
    failsafe = threading.Timer(0.5, release_write.set)
    failsafe.start()
    started = asyncio.get_running_loop().time()
    task = asyncio.create_task(service.generate({"topic": "事件循环写入测试"}))
    try:
        assert await asyncio.to_thread(write_started.wait, 1)
        assert asyncio.get_running_loop().time() - started < 0.3
        release_write.set()
        await task
    finally:
        release_write.set()
        failsafe.cancel()


@pytest.mark.asyncio
async def test_live_mapping_resolves_server_provider_before_validation_and_records_meta(
    tmp_path: Path,
) -> None:
    captured: list[ProviderSettings | None] = []

    async def run_generate(command: GenerateRequest) -> GeneratedDocument:
        captured.append(command.provider)
        result = generate_demo(command.model_copy(update={"live": False}))
        return result.model_copy(
            update={
                "meta": GenerationMeta(
                    mode="live",
                    provider="reported-provider",
                    model="reported-model",
                    input_tokens=17,
                    output_tokens=9,
                    total_tokens=26,
                )
            }
        )

    storage = GongwenStorage(tmp_path / "live.sqlite3")
    runtime = RuntimeSettings(
        environment="test",
        server_provider=ProviderSettings(
            name="openai",
            model="server-model",
            api_key="SERVER_SECRET",
            base_url="https://server.example.test/v1",
            timeout_seconds=30,
            options={"organization": "fixture"},
        ),
    )
    times = iter((10.0, 10.25))
    service = GongwenService(
        storage,
        runtime,
        generate_live_fn=run_generate,
        clock=lambda: next(times),
    )

    result = await service.generate(
        {
            "topic": "服务端模型",
            "live": True,
            "provider": {
                "name": "ignored-client-name",
                "model": "client-selected-model",
                "base_url": "https://ignored.example.test/v1",
                "timeout_seconds": 12,
            },
        }
    )

    assert result.meta.total_tokens == 26
    assert len(captured) == 1
    provider = captured[0]
    assert provider is not None
    assert provider.name == "openai"
    assert provider.model == "client-selected-model"
    assert provider.api_key == "SERVER_SECRET"
    assert provider.base_url == "https://server.example.test/v1"
    assert provider.timeout_seconds == 12
    assert provider.options == {"organization": "fixture"}

    usage = storage.list_model_usage(limit=10)
    assert len(usage) == 1
    assert usage[0]["operation"] == "generate"
    assert usage[0]["provider"] == "reported-provider"
    assert usage[0]["model"] == "reported-model"
    assert usage[0]["input_tokens"] == 17
    assert usage[0]["output_tokens"] == 9
    assert usage[0]["total_tokens"] == 26
    assert usage[0]["latency_ms"] == 250.0
    assert "SERVER_SECRET" not in str(usage)


@pytest.mark.asyncio
async def test_live_title_and_probe_use_server_provider_without_client_settings(
    tmp_path: Path,
) -> None:
    title_providers: list[ProviderSettings | None] = []
    probe_providers: list[ProviderSettings] = []

    async def run_titles(command: TitleGenerationRequest) -> TitleGenerationResult:
        title_providers.append(command.provider)
        result = generate_titles_demo(command.model_copy(update={"live": False}))
        return result.model_copy(
            update={"meta": GenerationMeta(mode="live", provider="openai", model="model-v1")}
        )

    async def run_probe(provider: ProviderSettings) -> ProviderProbeResult:
        probe_providers.append(provider)
        return ProviderProbeResult(
            meta=GenerationMeta(mode="live", provider=provider.name, model=provider.model)
        )

    storage = GongwenStorage(tmp_path / "title-probe.sqlite3")
    runtime = RuntimeSettings(
        environment="test",
        server_provider=ProviderSettings(
            name="openai",
            model="model-v1",
            api_key="SERVER_SECRET",
        ),
    )
    service = GongwenService(
        storage,
        runtime,
        generate_titles_live_fn=run_titles,
        probe_provider_fn=run_probe,
    )

    titles = await service.generate_titles({"topic": "重点项目调度", "live": True})
    probe = await service.probe_provider()

    assert titles.meta.mode == "live"
    assert probe.ok is True
    assert title_providers[0] is not None
    assert title_providers[0].api_key == "SERVER_SECRET"
    assert probe_providers[0].api_key == "SERVER_SECRET"
    assert {item["operation"] for item in storage.list_model_usage(limit=10)} == {
        "titles",
        "provider_probe",
    }


@pytest.mark.asyncio
async def test_live_failure_is_recorded_without_exception_text_or_secret(tmp_path: Path) -> None:
    failure = ProviderTimeoutError(
        "upstream response contained PRIVATE_MATERIAL",
        provider="fixture",
    )

    async def fail(_: GenerateRequest) -> GeneratedDocument:
        raise failure

    storage = GongwenStorage(tmp_path / "failure.sqlite3")
    service = GongwenService(
        storage,
        RuntimeSettings(environment="test"),
        generate_live_fn=fail,
    )

    with pytest.raises(ProviderTimeoutError) as raised:
        await service.generate(
            {
                "topic": "PRIVATE_MATERIAL",
                "live": True,
                "provider": {
                    "name": "fixture",
                    "model": "fixture-model",
                    "api_key": "CLIENT_SECRET",
                },
            }
        )

    assert raised.value is failure
    usage = storage.list_model_usage(limit=10)
    assert len(usage) == 1
    assert usage[0]["operation"] == "generate"
    assert usage[0]["provider"] == "fixture"
    assert usage[0]["model"] == "fixture-model"
    assert usage[0]["success"] is False
    assert usage[0]["error_code"] == "ProviderTimeoutError"
    assert usage[0]["metadata"] == {"mode": "live"}
    assert "PRIVATE_MATERIAL" not in str(usage)
    assert "CLIENT_SECRET" not in str(usage)


def test_provider_payload_resolution_preserves_original_live_semantics(tmp_path: Path) -> None:
    service = GongwenService(
        GongwenStorage(tmp_path / "payload.sqlite3"),
        RuntimeSettings(
            environment="test",
            server_provider=ProviderSettings(
                name="openai",
                model="fixture-model",
                api_key="SERVER_SECRET",
            ),
        ),
    )

    for live_value in (True, 1, "true", "TRUE"):
        resolved = service.resolve_provider_payload({"live": live_value})
        assert resolved["provider"] == {
            "name": "openai",
            "model": "fixture-model",
            "api_key": "SERVER_SECRET",
            "options": {},
        }

    for live_value in (False, 0, "false"):
        assert "provider" not in service.resolve_provider_payload({"live": live_value})

    forced = service.resolve_provider_payload({}, force=True)
    assert forced["provider"] == {
        "name": "openai",
        "model": "fixture-model",
        "api_key": "SERVER_SECRET",
        "options": {},
    }
