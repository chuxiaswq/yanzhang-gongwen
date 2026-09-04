"""Provider-neutral, deterministic model routing presets."""

# Chinese routing descriptions intentionally use full-width punctuation.
# ruff: noqa: RUF001

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from yanzhang_core.models import CoreModel, ModelProfile, ModelTier

type RoutingPresetName = Literal["economy", "balanced", "quality", "local_only"]


class RoutingPreset(CoreModel):
    """A stable policy describing tier preference and network constraints."""

    id: RoutingPresetName
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    preferred_tiers: tuple[ModelTier, ...] = Field(min_length=1, max_length=4)
    allow_remote: bool


class ModelRouteRequest(CoreModel):
    """Task requirements supplied to the local router."""

    preset: RoutingPresetName = "balanced"
    required_capabilities: tuple[str, ...] = Field(default=("drafting",), max_length=16)
    preferred_profile_id: str | None = Field(default=None, min_length=1, max_length=100)
    contains_sensitive_data: bool = False

    @field_validator("required_capabilities")
    @classmethod
    def validate_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in values)
        if any(not item for item in cleaned):
            raise ValueError("required_capabilities 不得包含空值")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("required_capabilities 不得重复")
        return cleaned


class RoutingDecision(CoreModel):
    """The selected non-secret profile plus observable routing reasoning."""

    preset: RoutingPresetName
    profile: ModelProfile
    reason: str = Field(min_length=1, max_length=500)
    allows_network: bool
    fallback_profile_ids: tuple[str, ...]


ROUTING_PRESETS: tuple[RoutingPreset, ...] = (
    RoutingPreset(
        id="economy",
        name="经济优先",
        description="优先低成本、低延迟画像，并保留本地回退。",
        preferred_tiers=("economy", "local", "balanced", "quality"),
        allow_remote=True,
    ),
    RoutingPreset(
        id="balanced",
        name="均衡",
        description="在质量、速度和成本之间保持均衡。",
        preferred_tiers=("balanced", "quality", "economy", "local"),
        allow_remote=True,
    ),
    RoutingPreset(
        id="quality",
        name="质量优先",
        description="优先具备高质量和长上下文能力的画像。",
        preferred_tiers=("quality", "balanced", "economy", "local"),
        allow_remote=True,
    ),
    RoutingPreset(
        id="local_only",
        name="仅本地",
        description="只选择本地画像，任务内容不经过远程模型路由。",
        preferred_tiers=("local",),
        allow_remote=False,
    ),
)


DEFAULT_MODEL_PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile(
        id="local-deterministic",
        name="本地确定性引擎",
        provider="local",
        model="deterministic",
        tier="local",
        capabilities=("headlines", "drafting", "rewrite", "review"),
        privacy_mode="local",
        cost_rank=0,
        quality_rank=45,
        latency_rank=95,
        max_context_tokens=32_000,
    ),
    ModelProfile(
        id="configured-economy",
        name="已配置经济模型",
        provider="configured",
        model="economy",
        tier="economy",
        capabilities=("headlines", "drafting", "rewrite", "review"),
        privacy_mode="server_managed",
        cost_rank=20,
        quality_rank=65,
        latency_rank=90,
        max_context_tokens=64_000,
    ),
    ModelProfile(
        id="configured-balanced",
        name="已配置均衡模型",
        provider="configured",
        model="balanced",
        tier="balanced",
        capabilities=("headlines", "drafting", "rewrite", "review", "long_context"),
        privacy_mode="server_managed",
        cost_rank=50,
        quality_rank=82,
        latency_rank=72,
        max_context_tokens=128_000,
    ),
    ModelProfile(
        id="configured-quality",
        name="已配置高质量模型",
        provider="configured",
        model="quality",
        tier="quality",
        capabilities=("headlines", "drafting", "rewrite", "review", "long_context"),
        privacy_mode="server_managed",
        cost_rank=85,
        quality_rank=96,
        latency_rank=50,
        max_context_tokens=200_000,
    ),
)


def routing_presets() -> tuple[RoutingPreset, ...]:
    """Return every built-in routing policy."""

    return ROUTING_PRESETS


def get_routing_preset(preset_id: str) -> RoutingPreset:
    """Resolve one preset by id."""

    for preset in ROUTING_PRESETS:
        if preset.id == preset_id:
            return preset
    raise ValueError(f"未知模型路由预设：{preset_id}")


def route_model(
    request: ModelRouteRequest,
    profiles: tuple[ModelProfile, ...] = DEFAULT_MODEL_PROFILES,
) -> RoutingDecision:
    """Select a compatible enabled profile without contacting any provider."""

    preset = get_routing_preset(request.preset)
    required = set(request.required_capabilities)
    candidates = tuple(
        profile
        for profile in profiles
        if profile.enabled
        and required.issubset(profile.capabilities)
        and (preset.allow_remote or profile.privacy_mode == "local")
        and (not request.contains_sensitive_data or profile.privacy_mode == "local")
    )
    if not candidates:
        raise ValueError("没有满足路由策略和能力要求的模型画像")

    tier_order = {tier: index for index, tier in enumerate(preset.preferred_tiers)}
    candidates = tuple(profile for profile in candidates if profile.tier in tier_order)
    if not candidates:
        raise ValueError("路由预设未包含可用模型层级")

    preferred = next(
        (
            profile
            for profile in candidates
            if request.preferred_profile_id is not None
            and profile.id == request.preferred_profile_id
        ),
        None,
    )
    ranked = tuple(sorted(candidates, key=lambda profile: _profile_key(profile, tier_order)))
    selected = preferred or ranked[0]
    fallbacks = tuple(profile.id for profile in ranked if profile.id != selected.id)
    policy_reason = (
        "敏感任务按本地画像处理"
        if request.contains_sensitive_data
        else f"按“{preset.name}”预设选择首个满足能力要求的画像"
    )
    if preferred is not None:
        policy_reason = "优先画像满足当前预设、隐私和能力要求"
    return RoutingDecision(
        preset=request.preset,
        profile=selected,
        reason=policy_reason,
        allows_network=selected.privacy_mode != "local",
        fallback_profile_ids=fallbacks,
    )


def _profile_key(
    profile: ModelProfile, tier_order: dict[ModelTier, int]
) -> tuple[int, int, int, str]:
    if profile.tier == "economy":
        secondary = profile.cost_rank
        tertiary = -profile.latency_rank
    elif profile.tier == "quality":
        secondary = -profile.quality_rank
        tertiary = profile.cost_rank
    else:
        secondary = -profile.quality_rank
        tertiary = -profile.latency_rank
    return (tier_order[profile.tier], secondary, tertiary, profile.id)


__all__ = [
    "DEFAULT_MODEL_PROFILES",
    "ROUTING_PRESETS",
    "ModelRouteRequest",
    "RoutingDecision",
    "RoutingPreset",
    "RoutingPresetName",
    "get_routing_preset",
    "route_model",
    "routing_presets",
]
