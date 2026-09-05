"""Offline contracts for the shared Python/browser scenario catalog."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from scripts.build_scenario_catalog import build_catalog_javascript
from yanzhang_core import packs
from yanzhang_core.scenario_profiles import (
    get_scenario_profile,
    scenario_catalog,
    scenario_for_document_type,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG_ASSET = ROOT / "gongwen_web" / "static" / "scenario_catalog.js"
PACK_IDS = ("gongwen", "workplace", "media", "academic")
FORM_KEYS = {
    "topic",
    "purpose",
    "audience",
    "materials",
    "requirements",
    "keywords",
    "generate",
    "review",
    "reference_style",
}


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_scenario_profile_has_complete_form_and_review_contract(pack_id: str) -> None:
    profile = get_scenario_profile(pack_id)
    data = profile.model_dump(mode="json")

    assert isinstance(profile, BaseModel)
    assert data["id"] == pack_id
    assert data["name"].strip()
    assert data["description"].strip()
    assert data["styles"]
    assert all(set(style) == {"id", "label", "description"} for style in data["styles"])
    assert all(value.strip() for style in data["styles"] for value in style.values())
    style_ids = [style["id"] for style in data["styles"]]
    style_labels = [style["label"] for style in data["styles"]]
    assert len(style_ids) == len(set(style_ids))
    assert len(style_labels) == len(set(style_labels))
    assert data["default_style"] in style_labels
    assert data["tones"]
    assert all(isinstance(tone, str) and tone.strip() for tone in data["tones"])
    assert len(data["tones"]) == len(set(data["tones"]))
    assert data["default_tone"] in data["tones"]

    assert set(data["source"]) == {"title", "description", "action_label", "action"}
    assert all(value.strip() for value in data["source"].values())
    assert data["source"]["action"] in {"articles", "materials", "academic"}
    for field in ("labels", "placeholders"):
        assert set(data[field]) == FORM_KEYS
        assert all(isinstance(value, str) and value.strip() for value in data[field].values())
    for field, expected_count in (("checklist", 6), ("review_dimensions", 4)):
        assert len(data[field]) == expected_count
        assert all(isinstance(value, str) and value.strip() for value in data[field])
        assert len(data[field]) == len(set(data[field]))
    assert set(data["example"]) == {
        "topic",
        "purpose",
        "audience",
        "materials",
        "requirements",
        "keywords",
    }
    assert all(isinstance(value, str) and value.strip() for value in data["example"].values())
    assert isinstance(data["prompt_guidance"], list)
    assert data["prompt_guidance"]
    assert all(isinstance(value, str) and value.strip() for value in data["prompt_guidance"])


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_scenario_profiles_are_frozen(pack_id: str) -> None:
    profile = get_scenario_profile(pack_id)
    original = profile.model_dump(mode="json")

    with pytest.raises(ValidationError, match="frozen_instance"):
        profile.name = "changed"

    assert get_scenario_profile(pack_id).model_dump(mode="json") == original


@pytest.mark.parametrize(
    ("pack_id", "minimum_styles"), (("workplace", 6), ("media", 5), ("academic", 6))
)
def test_non_gongwen_scenarios_have_distinct_style_choices(
    pack_id: str, minimum_styles: int
) -> None:
    assert len(get_scenario_profile(pack_id).styles) >= minimum_styles


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_recipe_styles_cover_exactly_the_scenarios_canonical_recipes(pack_id: str) -> None:
    profile = get_scenario_profile(pack_id)
    recipe_styles = profile.model_dump(mode="json")["recipe_styles"]
    canonical_ids = {recipe.id for recipe in packs.get_scenario_pack(pack_id).recipes}
    style_labels = {style.label for style in profile.styles}

    assert isinstance(recipe_styles, dict)
    assert set(recipe_styles) == canonical_ids
    assert all(isinstance(label, str) and label in style_labels for label in recipe_styles.values())


def test_recipe_style_recommendations_cover_all_nineteen_recipes_once() -> None:
    recommendation_ids = [
        recipe_id
        for pack_id in PACK_IDS
        for recipe_id in get_scenario_profile(pack_id).recipe_styles
    ]
    canonical_ids = {recipe.id for recipe in packs.list_recipes()}

    assert len(recommendation_ids) == len(set(recommendation_ids)) == 19
    assert set(recommendation_ids) == canonical_ids


@pytest.mark.parametrize(
    ("pack_id", "recipe_id", "expected_style"),
    (
        ("workplace", "work-email", "行动邮件"),
        ("media", "press-release", "倒金字塔新闻"),
        ("academic", "research-abstract", "结构化摘要"),
        ("academic", "reviewer-response", "逐条审稿回复"),
    ),
)
def test_high_frequency_recipes_recommend_the_matching_writing_method(
    pack_id: str, recipe_id: str, expected_style: str
) -> None:
    assert get_scenario_profile(pack_id).recipe_styles[recipe_id] == expected_style


@pytest.mark.parametrize("pack_id", PACK_IDS)
@pytest.mark.parametrize(
    "invalid_case",
    ("missing_recipe", "extra_recipe", "foreign_recipe", "unknown_style", "foreign_style"),
)
def test_profile_validation_rejects_invalid_recipe_style_mappings(
    pack_id: str, invalid_case: str
) -> None:
    profile = get_scenario_profile(pack_id)
    data = profile.model_dump(mode="json")
    recipe_styles = data["recipe_styles"]
    first_recipe_id = packs.get_scenario_pack(pack_id).recipes[0].id
    if invalid_case == "missing_recipe":
        del recipe_styles[first_recipe_id]
    elif invalid_case == "extra_recipe":
        recipe_styles["not-a-canonical-recipe"] = profile.default_style
    elif invalid_case == "foreign_recipe":
        foreign_recipe = next(
            recipe for recipe in packs.list_recipes() if recipe.pack_id != pack_id
        )
        del recipe_styles[first_recipe_id]
        recipe_styles[foreign_recipe.id] = profile.default_style
    elif invalid_case == "unknown_style":
        recipe_styles[first_recipe_id] = "not-a-canonical-style"
    else:
        own_labels = {style.label for style in profile.styles}
        foreign_label = next(
            style.label
            for other_pack_id in PACK_IDS
            if other_pack_id != pack_id
            for style in get_scenario_profile(other_pack_id).styles
            if style.label not in own_labels
        )
        recipe_styles[first_recipe_id] = foreign_label

    with pytest.raises(ValidationError):
        type(profile).model_validate(data)


@pytest.mark.parametrize("field", ("default_style", "default_tone"))
def test_profile_validation_rejects_default_choices_outside_its_options(field: str) -> None:
    profile = get_scenario_profile("workplace")
    data = profile.model_dump(mode="json")
    data[field] = "not-an-existing-choice"

    with pytest.raises(ValidationError):
        type(profile).model_validate(data)


@pytest.mark.parametrize("field", ("id", "label"))
def test_profile_validation_rejects_duplicate_style_choices(field: str) -> None:
    profile = get_scenario_profile("workplace")
    data = profile.model_dump(mode="json")
    data["styles"][1][field] = data["styles"][0][field]

    with pytest.raises(ValidationError):
        type(profile).model_validate(data)


@pytest.mark.parametrize("pack_id", ("unknown", "", "not-a-pack"))
def test_unknown_pack_id_is_rejected(pack_id: str) -> None:
    with pytest.raises(ValueError):
        get_scenario_profile(pack_id)


@pytest.mark.parametrize(
    ("document_type", "pack_id"),
    (
        ("通知", "gongwen"),
        ("请示", "gongwen"),
        ("报告", "gongwen"),
        ("函", "gongwen"),
        ("邮件", "workplace"),
        ("工作邮件", "workplace"),
        ("职场邮件", "workplace"),
        ("周报", "workplace"),
        ("业务方案", "workplace"),
        ("商业方案", "workplace"),
        ("会议跟办", "workplace"),
        ("PPT提纲", "workplace"),
        ("新闻稿", "media"),
        ("公众号文章", "media"),
        ("社交媒体文案", "media"),
        ("短视频脚本", "media"),
        ("学术论文", "academic"),
        ("论文", "academic"),
        ("摘要", "academic"),
        ("论文摘要", "academic"),
        ("审稿回复", "academic"),
    ),
)
def test_document_type_aliases_resolve_to_the_matching_profile(
    document_type: str, pack_id: str
) -> None:
    assert scenario_for_document_type(document_type) == get_scenario_profile(pack_id)


@pytest.mark.parametrize("document_type", ("", "   ", "unknown-document-type"))
def test_unknown_document_type_defaults_to_neutral_workplace(document_type: str) -> None:
    assert scenario_for_document_type(document_type) == get_scenario_profile("workplace")


def test_catalog_is_json_serializable_and_contains_all_canonical_profiles() -> None:
    catalog = scenario_catalog()

    assert set(catalog) == {"schema_version", "profiles", "recipes"}
    assert catalog["schema_version"] == 1
    assert catalog["profiles"] == {
        pack_id: get_scenario_profile(pack_id).model_dump(mode="json") for pack_id in PACK_IDS
    }
    assert json.loads(json.dumps(catalog, ensure_ascii=False)) == catalog


def test_catalog_reuses_all_nineteen_pack_recipe_definitions() -> None:
    expected = {
        pack.id: [recipe.model_dump(mode="json") for recipe in pack.recipes]
        for pack in packs.list_scenario_packs()
    }

    assert tuple(expected) == PACK_IDS
    assert sum(len(recipes) for recipes in expected.values()) == 19
    assert scenario_catalog()["recipes"] == expected


def test_catalog_reads_recipes_from_the_pack_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    original_packs = packs.list_scenario_packs()
    original_pack = original_packs[0]
    updated_recipe = original_pack.recipes[0].model_copy(
        update={"summary": "Offline registry mutation proves the single recipe source."}
    )
    updated_pack = original_pack.model_copy(
        update={"recipes": (updated_recipe, *original_pack.recipes[1:])}
    )
    monkeypatch.setattr(packs, "SCENARIO_PACKS", (updated_pack, *original_packs[1:]))

    assert scenario_catalog()["recipes"] == {
        pack.id: [recipe.model_dump(mode="json") for recipe in pack.recipes]
        for pack in packs.list_scenario_packs()
    }


def test_catalog_payload_mutation_leaves_canonical_data_unchanged() -> None:
    original = scenario_catalog()
    original_academic_profile = get_scenario_profile("academic").model_dump(mode="json")
    changed = scenario_catalog()
    profiles = changed["profiles"]
    recipes = changed["recipes"]
    assert isinstance(profiles, dict)
    assert isinstance(recipes, dict)
    academic = profiles["academic"]
    workplace_recipes = recipes["workplace"]
    assert isinstance(academic, dict)
    assert isinstance(workplace_recipes, list)
    first_recipe = workplace_recipes[0]
    assert isinstance(first_recipe, dict)
    academic["name"] = "changed"
    first_recipe["name"] = "changed"
    recipe_styles = academic["recipe_styles"]
    assert isinstance(recipe_styles, dict)
    recipe_styles["research-abstract"] = "changed"
    recipe_styles["not-a-canonical-recipe"] = "changed"

    assert scenario_catalog() == original
    assert get_scenario_profile("academic").model_dump(mode="json") == original_academic_profile


def test_checked_in_browser_catalog_matches_the_deterministic_generator() -> None:
    expected = build_catalog_javascript()

    assert CATALOG_ASSET.read_text(encoding="utf-8") == expected
    assert build_catalog_javascript() == expected


@pytest.mark.parametrize("environment", ("commonjs", "browser"))
def test_browser_and_commonjs_exports_equal_the_python_catalog(environment: str) -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the browser catalog contract tests"
    script = """
const path = process.argv[1];
const environment = process.argv[2];
let catalog;
if (environment === "commonjs") {
  catalog = require(path);
} else {
  const fs = require("node:fs");
  const vm = require("node:vm");
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path, "utf8"), context);
  catalog = context.YanzhangScenarioCatalog;
}
process.stdout.write(JSON.stringify(catalog));
"""
    completed = subprocess.run(
        [node, "-e", script, str(CATALOG_ASSET), environment],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout) == scenario_catalog()
