"""Offline contract tests for the general writing model gateway."""

from __future__ import annotations

import pytest

from gongwen_web.model_gateway import ModelGatewayError, RuntimeModelCallback, build_model_callback
from gongwen_web.models import ProviderSettings
from gongwen_web.runtime import RuntimeSettings
from yanzhang.providers.llm.fake import FakeLLMProvider
from yanzhang.providers.registry import ProviderRegistry


@pytest.mark.asyncio
async def test_runtime_callback_uses_registry_and_closes_provider() -> None:
    provider = FakeLLMProvider(responses=("  已生成的母稿  ",))
    registry = ProviderRegistry()
    registry.register_llm("fake", lambda model=None: provider)
    settings = RuntimeSettings(
        environment="test",
        server_provider=ProviderSettings(
            name="fake",
            model="fixture-model",
            api_key="fixture-secret",
        ),
    )

    callback = RuntimeModelCallback(settings, registry=registry)
    result = await callback("只处理输入数据", "请生成母稿")

    assert result == "已生成的母稿"
    assert provider.calls[0].model == "fixture-model"
    assert provider.calls[0].messages[0].text == "只处理输入数据"
    assert provider.calls[0].messages[1].text == "请生成母稿"


def test_callback_is_only_built_for_complete_server_configuration() -> None:
    assert build_model_callback(RuntimeSettings(environment="test")) is None


@pytest.mark.asyncio
async def test_callback_validates_prompts_before_provider_construction() -> None:
    settings = RuntimeSettings(
        environment="test",
        server_provider=ProviderSettings(
            name="fake",
            model="fixture-model",
            api_key="fixture-secret",
        ),
    )
    callback = RuntimeModelCallback(settings, registry=ProviderRegistry())

    with pytest.raises(ModelGatewayError, match="提示词"):
        await callback("", "task")
