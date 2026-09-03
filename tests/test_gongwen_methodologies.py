"""Offline contracts for title-first and methodology-driven writing."""

# Chinese official-document test data intentionally uses full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import gongwen_web.live as live
from gongwen_web.app import create_app
from gongwen_web.demo import generate_demo
from gongwen_web.methodologies import methodology_catalog
from gongwen_web.models import GenerateRequest, ProviderSettings
from gongwen_web.storage import GongwenStorage
from gongwen_web.title_engine import TitleGenerationRequest, generate_titles_demo
from yanzhang.providers.llm.base import LLMResponse
from yanzhang.providers.llm.fake import FakeLLMProvider
from yanzhang.providers.registry import ProviderRegistry


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """Serve methodology endpoints with an isolated local usage database."""

    storage = GongwenStorage(tmp_path / "methodologies.sqlite3")
    with TestClient(create_app(storage=storage)) as test_client:
        yield test_client


def test_catalog_is_typed_filterable_and_has_document_defaults() -> None:
    catalog = methodology_catalog("通知")

    assert catalog.document_type == "通知"
    assert catalog.default_content_methodology_id == "notice-task-chain"
    assert catalog.default_title_formula_ids[0] == "formal-elements"
    assert all(
        "通知" in formula.applicable_document_types or "*" in formula.applicable_document_types
        for formula in catalog.title_formulas
    )
    assert any(item.id == "universal-problem-solving" for item in catalog.content_methodologies)
    assert {"主题相关", "文种规范", "信息密度", "简洁凝练", "节奏辨识"} <= set(
        catalog.title_scoring_dimensions
    )


def test_offline_title_batch_is_repeatable_ranked_and_explainable() -> None:
    command = TitleGenerationRequest(
        document_type="通知",
        topic="基层治理数字化提升",
        purpose="部署重点任务",
        materials="已完成6项事项整合。",
        count=5,
    )

    first = generate_titles_demo(command)
    second = generate_titles_demo(command)

    assert first == second
    assert first.recommended_title == "关于基层治理数字化提升的通知"
    assert len(first.candidates) == 5
    assert [item.rank for item in first.candidates] == [1, 2, 3, 4, 5]
    assert first.candidates[0].selected is True
    assert [item.score for item in first.candidates] == sorted(
        (item.score for item in first.candidates), reverse=True
    )
    assert sum(first.scoring_weights.values()) == 100
    assert all(item.scores.topic_relevance >= 90 for item in first.candidates)
    assert all(item.formula_id for item in first.candidates)


def test_custom_title_formula_and_reference_titles_affect_structure_without_copying() -> None:
    command = TitleGenerationRequest(
        document_type="工作总结",
        topic="数字政府建设",
        purpose="总结成效",
        count=6,
        custom_title_formula={
            "name": "主题目的式",
            "template": "{topic}：{purpose}",
            "rule": "先点主题，再用冒号交代写作目的",
            "style": "用户公式",
        },
        style_references=[
            {
                "title": "砥砺深耕谱新篇——某项工作观察",
                "source_name": "示例来源",
            }
        ],
    )

    result = generate_titles_demo(command)

    custom = next(item for item in result.candidates if item.formula_id == "custom")
    assert custom.title == "数字政府建设：总结成效"
    assert "用户公式" in custom.reason
    assert result.reference_profile is not None
    assert result.reference_profile.preferred_structure == "subtitle"
    assert any(item.formula_id == "reference-structure" for item in result.candidates)
    assert all("砥砺深耕" not in item.title for item in result.candidates)

    rule_only = generate_titles_demo(
        TitleGenerationRequest(
            document_type="讲话稿",
            topic="作风建设",
            count=3,
            custom_title_formula={"rule": "采用主副标题形式"},
        )
    )
    assert any(
        item.formula_id == "custom" and item.title.endswith("——作风建设")
        for item in rule_only.candidates
    )


def test_full_draft_uses_selected_title_and_built_in_or_custom_methodology() -> None:
    selected = "数字治理专项进展报告"
    custom = generate_demo(
        GenerateRequest(
            document_type="报告",
            topic="数字治理",
            selected_title=selected,
            materials="已完成6项任务。下一步计划于9月底前完成验收。",
            custom_methodology={
                "name": "证据三步法",
                "summary": "用三个连续步骤形成闭环。",
                "logic": "摸清底数 → 分析原因 → 部署任务",
                "steps": ["摸清底数", "分析原因", "部署任务"],
            },
        )
    )

    assert custom.title == selected
    assert custom.title_candidates[0].title == selected
    assert custom.title_candidates[0].selected is True
    assert [item.heading for item in custom.outline] == [
        "一、摸清底数",
        "二、分析原因",
        "三、部署任务",
    ]
    assert custom.content_methodology is not None
    assert custom.content_methodology.source == "custom"
    assert custom.content_methodology.logic == "摸清底数 → 分析原因 → 部署任务"
    assert any(card.source_type == "用户自定义内容方法论" for card in custom.source_cards)

    built_in = generate_demo(
        GenerateRequest(
            document_type="工作总结",
            topic="数字治理",
            content_methodology_id="universal-problem-solving",
        )
    )
    assert [item.heading for item in built_in.outline] == [
        "一、总体情况",
        "二、主要问题",
        "三、重点举措",
        "四、保障机制",
    ]
    assert built_in.content_methodology is not None
    assert built_in.content_methodology.id == "universal-problem-solving"


def test_methodology_and_title_http_endpoints_are_strict_and_offline(
    client: TestClient,
) -> None:
    catalog_response = client.get("/api/methodologies", params={"document_type": "实施方案"})
    assert catalog_response.status_code == 200
    assert catalog_response.headers["cache-control"] == "no-store"
    assert catalog_response.json()["default_content_methodology_id"] == "plan-goal-roadmap"

    title_response = client.post(
        "/api/titles/generate",
        json={
            "document_type": "通知",
            "topic": "重点项目调度",
            "materials": "计划于9月底前完成验收。",
            "count": 5,
            "live": False,
        },
    )
    assert title_response.status_code == 200
    body = title_response.json()
    assert body["meta"]["mode"] == "demo"
    assert len(body["candidates"]) == 5
    assert body["recommended_title"] == body["candidates"][0]["title"]
    assert "information_density" in body["candidates"][0]["scores"]
    assert "rhythm" in body["candidates"][0]["scores"]

    extra_field = client.post(
        "/api/titles/generate",
        json={"topic": "严格输入", "unknown": True},
    )
    assert extra_field.status_code == 422
    assert extra_field.json()["error"]["code"] == "invalid_request"

    invalid_formula = client.post(
        "/api/titles/generate",
        json={"document_type": "通知", "topic": "严格公式", "formula_ids": ["missing"]},
    )
    assert invalid_formula.status_code == 400
    assert "未知标题公式" in invalid_formula.json()["error"]["message"]


class _ClosingFakeLLMProvider(FakeLLMProvider):
    def __init__(self, *, responses: Iterable[str | LLMResponse]) -> None:
        super().__init__(model="fixture-default", responses=responses)
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1


@pytest.mark.asyncio
async def test_live_title_contract_is_closed_and_scored_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ClosingFakeLLMProvider(
        responses=[
            json.dumps(
                {
                    "candidates": [
                        {
                            "title": "关于数字治理的报告",
                            "formula_id": "formal-elements",
                            "formula_name": "要素完整式",
                            "style": "要素完整",
                            "reason": "主题和文种完整",
                        },
                        {
                            "title": "关于扎实推进数字治理工作的报告",
                            "formula_id": "formal-action",
                            "formula_name": "行动部署式",
                            "style": "执行导向",
                            "reason": "行动导向明确",
                        },
                    ]
                },
                ensure_ascii=False,
            )
        ]
    )
    registry = ProviderRegistry()
    registry.register_llm("fixture", lambda **_config: provider)
    monkeypatch.setattr(live, "get_default_registry", lambda: registry)
    request = TitleGenerationRequest(
        document_type="报告",
        topic="数字治理",
        count=2,
        style_references=[{"title": "奋楫笃行开新局——示例观察", "source_name": "示例来源"}],
        live=True,
        provider=ProviderSettings(name="fixture", model="fixture-model", api_key="SECRET"),
    )

    result = await live.generate_titles_live(request)

    assert result.meta.mode == "live"
    assert result.candidates[0].score >= result.candidates[1].score
    assert sum(result.scoring_weights.values()) == 100
    assert provider.close_count == 1
    system_prompt, user_prompt = provider.calls[0].messages
    assert "不要输出评分" in system_prompt.text
    assert "reference_title_structure" in user_prompt.text
    assert "奋楫笃行" not in user_prompt.text
    assert "SECRET" not in system_prompt.text + user_prompt.text


@pytest.mark.asyncio
async def test_live_draft_enforces_an_explicit_custom_methodology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = "关于数字治理的报告"
    valid_provider = _ClosingFakeLLMProvider(
        responses=[
            json.dumps(
                {
                    "title": selected,
                    "outline": [
                        {"heading": "一、摸清底数", "content": "根据材料摸清底数。"},
                        {"heading": "二、部署任务", "content": "按既定要求部署任务。"},
                    ],
                    "content": (
                        "一、摸清底数\n根据材料摸清底数。\n\n二、部署任务\n按既定要求部署任务。"
                    ),
                },
                ensure_ascii=False,
            )
        ]
    )
    registry = ProviderRegistry()
    registry.register_llm("fixture", lambda **_config: valid_provider)
    monkeypatch.setattr(live, "get_default_registry", lambda: registry)
    request = GenerateRequest(
        document_type="报告",
        topic="数字治理",
        selected_title=selected,
        custom_methodology={
            "name": "双步闭环法",
            "logic": "摸底 → 部署",
            "steps": ["摸清底数", "部署任务"],
        },
        live=True,
        provider=ProviderSettings(name="fixture", api_key="SECRET"),
    )

    result = await live.generate_live(request)

    assert [item.heading for item in result.outline] == ["一、摸清底数", "二、部署任务"]
    assert result.content_methodology is not None
    assert result.content_methodology.source == "custom"
    system_prompt, user_prompt = valid_provider.calls[0].messages
    assert "enforce_content_methodology为true" in system_prompt.text
    assert '"enforce_content_methodology":true' in user_prompt.text
    assert "摸底 → 部署" in user_prompt.text

    invalid_provider = _ClosingFakeLLMProvider(
        responses=[
            json.dumps(
                {
                    "title": selected,
                    "outline": [{"heading": "一、自由结构", "content": "自由结构。"}],
                    "content": "一、自由结构\n自由结构。",
                },
                ensure_ascii=False,
            )
        ]
    )
    invalid_registry = ProviderRegistry()
    invalid_registry.register_llm("fixture", lambda **_config: invalid_provider)
    monkeypatch.setattr(live, "get_default_registry", lambda: invalid_registry)

    with pytest.raises(live.LiveRequestError, match="未按所选内容方法论组织"):
        await live.generate_live(request)

    assert invalid_provider.close_count == 1
