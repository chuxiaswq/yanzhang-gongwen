"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const catalog = require("../../gongwen_web/static/scenario_catalog.js");
const workspace = require("../../gongwen_web/static/scenario_workspace.js");

const sceneIds = ["gongwen", "workplace", "media", "academic"];
const politicalBoilerplate = /人民日报|光明日报|求是|政绩观|提高站位|凝聚思想共识|实干担当|为民答卷|干部群众|压实责任|守正创新/;

function freeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

function currentFor(id) {
  const profile = workspace.profile(id);
  return {
    materials: `${id} 的原始材料，保留全部内容`,
    topic: `${id} 主题`, purpose: `${id} 目标`, audience: `${id} 读者`,
    requirements: `${id} 独立约束`,
    reference_style: profile.styles[profile.styles.length - 1].label,
    style_custom: true,
    tone: profile.tones[profile.tones.length - 1],
    styleReferences: id === "academic" ? [] : [{ id: `${id}-reference`, excerpt: `${id} 范例片段` }],
  };
}

test("all four profiles expose coherent scene-owned styles, tones and source actions", () => {
  assert.deepEqual(Object.keys(catalog.profiles), sceneIds);
  const expectedActions = { gongwen: "articles", workplace: "materials", media: "materials", academic: "academic" };
  for (const id of sceneIds) {
    const profile = workspace.profile(id);
    assert.equal(profile.id, id);
    assert.ok(profile.name);
    assert.ok(profile.styles.some((style) => style.label === profile.default_style));
    assert.ok(profile.tones.includes(profile.default_tone));
    assert.equal(profile.source.action, expectedActions[id]);
    assert.equal(new Set(profile.styles.map((style) => style.id)).size, profile.styles.length);
    if (id !== "gongwen") {
      assert.doesNotMatch(profile.styles.map((style) => style.label).join(" "), politicalBoilerplate);
    }
  }
});

test("the generated canonical catalog contains 19 distinct recipes belonging to their scene", () => {
  const ids = new Set();
  const counts = { gongwen: 6, workplace: 5, media: 4, academic: 4 };
  for (const id of sceneIds) {
    assert.equal(catalog.recipes[id].length, counts[id]);
    for (const recipe of catalog.recipes[id]) {
      assert.equal(recipe.pack_id, id);
      assert.equal(ids.has(recipe.id), false);
      ids.add(recipe.id);
      assert.ok(recipe.content_type);
      assert.ok(recipe.sections.length > 0);
      assert.equal(workspace.inferScenario(recipe.content_type), id);
    }
  }
  assert.equal(ids.size, 19);
});

test("successive scene changes isolate input buffers and preserve the original materials", () => {
  let preferences = {};
  let current = currentFor("gongwen");
  const originals = { gongwen: structuredClone(current) };
  for (const [from, to] of [["gongwen", "workplace"], ["workplace", "media"], ["media", "academic"], ["academic", "gongwen"]]) {
    const input = freeze({ from, to, recipeId: catalog.recipes[to][0].id, preferences, current });
    const before = JSON.stringify(input);
    const result = workspace.transition(input);
    assert.equal(JSON.stringify(input), before);
    assert.deepEqual(result.preferences[from], originals[from]);
    assert.equal(result.preferences[from].materials, originals[from].materials);
    if (to === "gongwen") {
      assert.deepEqual(result.values, originals.gongwen);
    } else {
      assert.equal(result.values.materials, undefined);
      assert.equal(result.values.topic, undefined);
      assert.deepEqual(result.values.styleReferences, []);
    }
    preferences = result.preferences;
    current = { ...result.values, ...currentFor(to) };
    originals[to] = structuredClone(current);
  }
  for (const id of sceneIds) {
    assert.equal(preferences[id].materials, originals[id].materials);
    assert.equal(preferences[id].reference_style, originals[id].reference_style);
    assert.equal(preferences[id].tone, originals[id].tone);
  }
  preferences.gongwen.styleReferences[0].excerpt = "output edited independently";
  assert.equal(originals.gongwen.styleReferences[0].excerpt, "gongwen 范例片段");
});

test("scene defaults recommend the recipe style until the user explicitly chooses a valid style", () => {
  for (const id of sceneIds) {
    const profile = workspace.profile(id);
    for (const recipe of catalog.recipes[id]) {
      const automatic = workspace.transition({ from: id, to: id, recipeId: recipe.id, current: { reference_style: profile.styles[0].label } });
      assert.equal(automatic.values.reference_style, profile.recipe_styles[recipe.id] || profile.default_style);
      assert.equal(automatic.values.style_custom, false);
      assert.equal(automatic.values.tone, profile.default_tone);
      const selectedStyle = profile.styles[profile.styles.length - 1].label;
      const selectedTone = profile.tones[profile.tones.length - 1];
      const chosen = workspace.transition({ from: id, to: id, recipeId: recipe.id, current: {
        reference_style: selectedStyle, style_custom: true, tone: selectedTone,
      } });
      assert.equal(chosen.values.reference_style, selectedStyle);
      assert.equal(chosen.values.style_custom, true);
      assert.equal(chosen.values.tone, selectedTone);
    }
  }
});

test("invalid carried styles and tones are replaced with recommendations for the destination scene", () => {
  const result = workspace.transition({ from: "workplace", to: "workplace", recipeId: "work-email", current: {
    reference_style: "求是式理论论证", style_custom: true, tone: "严谨规范", materials: "原始业务材料",
  } });
  assert.equal(result.values.reference_style, "行动邮件");
  assert.equal(result.values.style_custom, false);
  assert.equal(result.values.tone, workspace.profile("workplace").default_tone);
  assert.equal(result.values.materials, "原始业务材料");
});

test("academic requests never receive saved style references and do not delete the saved input", () => {
  const saved = freeze({ academic: {
    materials: "真实研究笔记",
    reference_style: "主题式文献综述", style_custom: true,
    styleReferences: [{ id: "historical-style", excerpt: "旧写法参考" }],
  } });
  const before = JSON.stringify(saved);
  const result = workspace.transition({ from: "media", to: "academic", recipeId: "literature-review", preferences: saved, current: currentFor("media") });
  assert.deepEqual(result.values.styleReferences, []);
  assert.equal(result.values.materials, "真实研究笔记");
  assert.equal(JSON.stringify(saved), before);
  assert.equal(result.preferences.academic.styleReferences[0].id, "historical-style");
});

test("unknown documents and scenes use a neutral workplace profile", () => {
  for (const id of [undefined, "", "future-scene"]) assert.equal(workspace.profile(id).id, "workplace");
  assert.equal(workspace.inferScenario("未知材料"), "workplace");
  assert.equal(workspace.inferScenario("自定义学术论文"), "academic");
  assert.equal(workspace.inferScenario("通知"), "gongwen");
  const result = workspace.transition({ from: "gongwen", to: "future-scene", current: currentFor("gongwen") });
  assert.equal(result.values.reference_style, workspace.profile("workplace").default_style);
  assert.equal(result.values.tone, workspace.profile("workplace").default_tone);
  assert.equal(result.values.materials, undefined);
  assert.doesNotMatch(result.values.reference_style, politicalBoilerplate);
});

test("academic materials include only evidence linked to records in the current material package", () => {
  const input = freeze({
    records: [{ id: "r1", title: "真实文献", year: 2024, doi: "10.fixture/one" }],
    evidence: [
      { id: "e1", record_id: "r1", text: "匹配文献的原文片段", locator: "第 2 页" },
      { id: "e2", record_id: "other-record", text: "别的项目的证据内容", locator: "第 9 页" },
    ],
  });
  const before = JSON.stringify(input);
  const material = workspace.academicMaterials(input);
  assert.match(material, /\[文献 r1\]/);
  assert.match(material, /\[证据 e1｜文献 r1\]/);
  assert.match(material, /匹配文献的原文片段/);
  assert.match(material, /第 2 页/);
  assert.equal(material.includes("别的项目的证据内容"), false);
  assert.equal(material.includes("[证据 e2"), false);
  assert.match(material, /元数据仅用于识别文献，不证明研究结论/);
  assert.equal(JSON.stringify(input), before);
});

test("a bibliography without excerpts explicitly leaves findings unsupported", () => {
  assert.equal(workspace.academicMaterials(), "");
  const material = workspace.academicMaterials({ records: [{ id: "r1", title: "标题不是研究结论" }], evidence: [] });
  assert.match(material, /待补原文证据/);
  assert.match(material, /不生成文献发现或研究结果/);
  assert.match(material, /不凭标题推断结果/);
  const unmatched = workspace.academicMaterials({ records: [{ id: "r1" }], evidence: [{ id: "e1", record_id: "missing", text: "未关联片段" }] });
  assert.match(unmatched, /待补原文证据/);
  assert.equal(unmatched.includes("未关联片段"), false);
});

test("academic materials use the canonical literature schema year before legacy metadata", () => {
  const input = freeze({ records: [
    { id: "canonical", title: "正式书目记录", issued_year: 2025, year: 1999 },
    { id: "legacy", title: "旧记录", year: 2021 },
    { id: "undated", title: "无年份记录" },
  ] });
  const material = workspace.academicMaterials(input);
  assert.match(material, /\[文献 canonical\] 正式书目记录；年份：2025/);
  assert.match(material, /\[文献 legacy\] 旧记录；年份：2021/);
  assert.match(material, /\[文献 undated\] 无年份记录；年份：待核/);
  assert.equal(material.includes("1999"), false);
});

test("academic evidence keeps canonical section, page, paragraph and character locators including zero", () => {
  const input = freeze({ records: [{ id: "r1", title: "定位核验文献" }], evidence: [
    { id: "e1", record_id: "r1", text: "可定位原文甲", section: "方法", page_start: 2, page_end: 4, paragraph_index: 3, char_start: 12, char_end: 45 },
    { id: "e2", record_id: "r1", text: "可定位原文乙", page_start: 0, page_end: 0, paragraph_index: 0, char_start: 0, char_end: 0 },
    { id: "e3", record_id: "r1", text: "旧字段原文", locator: "附录 A 的第 3 段" },
    { id: "e4", record_id: "r1", text: "尚未定位原文" },
  ] });
  const before = JSON.stringify(input);
  const material = workspace.academicMaterials(input);
  assert.match(material, /定位：方法；页 2–4；段 3；字符 12–45/);
  assert.match(material, /定位：页 0–0；段 0；字符 0–0/);
  assert.match(material, /定位：附录 A 的第 3 段/);
  assert.match(material, /\[证据 e4｜文献 r1\] 尚未定位原文\n定位：待核/);
  assert.equal(JSON.stringify(input), before);
});

test("blank matching excerpts do not count as original evidence", () => {
  for (const text of [undefined, "", "   \n "]) {
    const material = workspace.academicMaterials({ records: [{ id: "r1" }], evidence: [{ id: "e1", record_id: "r1", text }] });
    assert.match(material, /待补原文证据/);
  }
});

test("academic package limits are explicit and omit evidence belonging to omitted records", () => {
  const records = Array.from({ length: 45 }, (_, index) => ({ id: `r${index + 1}`, title: `文献 ${index + 1}` }));
  const evidence = records.map((record, index) => ({ id: `e${index + 1}`, record_id: record.id, text: `证据内容 ${index + 1}` }));
  const material = workspace.academicMaterials({ records, evidence });
  assert.equal((material.match(/\[文献 r/g) || []).length, 40);
  assert.equal((material.match(/\[证据 e/g) || []).length, 40);
  assert.match(material, /40\/45 条文献及 40\/45 条证据/);
  assert.match(material, /其余内容未参与本次生成/);
  assert.equal(material.includes("证据内容 45"), false);
  assert.equal(material.includes("[文献 r45]"), false);
});

test("non-government expression candidates respect every focus and remain free of political boilerplate", () => {
  for (const id of ["workplace", "media", "academic"]) {
    for (const recipe of catalog.recipes[id]) {
      const headings = recipe.sections.map((section) => section.title);
      const input = freeze({ topic: "数据协作", goal: "明确研究范围", audience: "相关读者", headings });
      const before = JSON.stringify(input);
      for (const focus of ["title", "opening", "topic_sentence", "section_heading"]) {
        for (const count of [1, 3, 5, 8]) {
          const candidates = workspace.expressionCandidates(id, focus, input, count);
          const available = focus === "section_heading" ? new Set(headings).size : 5;
          assert.equal(candidates.length, Math.min(count, available), `${id}/${recipe.id}/${focus}/${count}`);
          assert.equal(new Set(candidates).size, candidates.length);
          candidates.forEach((text) => { assert.ok(text.trim()); assert.doesNotMatch(text, politicalBoilerplate); });
          if (focus === "section_heading") candidates.forEach((text) => assert.ok(headings.includes(text)));
        }
      }
      assert.equal(JSON.stringify(input), before);
    }
  }
});

test("expression candidate counts are bounded and duplicate supplied headings are removed", () => {
  const input = { headings: ["范围", "证据", "范围", "结论", ""] };
  assert.deepEqual(workspace.expressionCandidates("academic", "section_heading", input, 8), ["范围", "证据", "结论"]);
  assert.equal(workspace.expressionCandidates("workplace", "title", {}, 0).length, 1);
  assert.equal(workspace.expressionCandidates("workplace", "title", {}, -8).length, 1);
  const unknown = workspace.expressionCandidates("future-scene", "title", { topic: "数据协作" }, 5);
  assert.equal(unknown.length, 5);
  assert.doesNotMatch(unknown.join(" "), politicalBoilerplate);
});
