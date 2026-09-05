"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const catalog = require("../../gongwen_web/static/scenario_catalog.js");

const source = fs.readFileSync(path.join(__dirname, "../../gongwen_web/static/app.js"), "utf8");

function handler(name) {
  const start = source.search(new RegExp(`^  (?:async )?function ${name}\\(`, "m"));
  assert.ok(start >= 0, `missing handler: ${name}`);
  const next = source.slice(start + 1).search(/^  (?:async )?function /m);
  return source.slice(start, next < 0 ? source.lastIndexOf("})();") : start + 1 + next);
}

function loadHandlers(names, globals) {
  return vm.runInNewContext(`${names.map(handler).join("\n")}\n({${names.join(",")}})`, globals);
}

function element() {
  return {
    dataset: {}, textContent: "", value: "", hidden: false, children: [],
    replaceChildren(...children) { this.children = children; },
    append(...children) { this.children.push(...children); },
    addEventListener() {},
    classList: { add() {}, remove() {} },
  };
}

test("four-scene review labels select scores by semantic dimension rather than position or overall score", () => {
  const scores = { format: 61, logic: 72, evidence: 83, language: 94, clarity: 65, audience_tone: 76 };
  const expected = {
    gongwen: [["格式规范", "format"], ["结构完整", "logic"], ["事实一致", "evidence"], ["语言精炼", "language"]],
    workplace: [["结论清晰", "clarity"], ["信息组织", "logic"], ["事实一致", "evidence"], ["行动可执行", "format"]],
    media: [["读者价值", "audience_tone"], ["叙事结构", "logic"], ["事实一致", "evidence"], ["渠道适配", "format"]],
    academic: [["问题与论证", "logic"], ["结构与方法", "format"], ["证据与引用", "evidence"], ["学术表达", "language"]],
  };
  for (const [id, mapping] of Object.entries(expected)) {
    const appState = { review: {
      score: 100, overall_score: 100,
      dimensions: Object.entries(scores).reverse().map(([dimension, score]) => ({ dimension, score })),
    } };
    const ui = loadHandlers(["sceneReviewDimensionIds", "reviewDimensionText"], {
      appState, currentScenario: () => catalog.profiles[id],
    });
    const ids = Array.from(ui.sceneReviewDimensionIds());
    assert.deepEqual(ids, mapping.map(([, dimension]) => dimension));
    assert.deepEqual(catalog.profiles[id].review_dimensions, mapping.map(([label]) => label));
    ids.forEach((dimension) => assert.equal(ui.reviewDimensionText(dimension), `${scores[dimension]} 分`));
    appState.review.dimensions = [];
    ids.forEach((dimension) => assert.equal(ui.reviewDimensionText(dimension), "未单独评分"));
  }
});

test("review dimensions preserve zero scores and leave absent or invalid scores unscored", () => {
  const appState = { review: { overall_score: 98, dimensions: [] } };
  const ui = loadHandlers(["reviewDimensionText"], { appState });
  for (const score of [0, 34, 100]) {
    appState.review.dimensions = [{ dimension: "logic", score }];
    assert.equal(ui.reviewDimensionText("logic"), `${score} 分`);
  }
  for (const score of [undefined, null, "", NaN, Infinity, "not-a-score"]) {
    appState.review.dimensions = [{ dimension: "logic", score }];
    assert.equal(ui.reviewDimensionText("logic"), "未单独评分", `invalid score: ${String(score)}`);
  }
  appState.review = null;
  assert.equal(ui.reviewDimensionText("logic"), "未单独评分");
});

test("changing a task clears both checklist state and visible checkboxes without deleting source materials", () => {
  for (const discardDraft of [false, true]) {
    const checkboxes = Array.from({ length: 6 }, () => ({ checked: true }));
    const appState = {
      form: { materials: "已保存的原始材料" },
      document: { title: "上一版", html: "<p>旧正文</p>", candidates: ["旧候选"], execution: { mode: "local" } },
      checklist: Array(6).fill(true), review: { score: 98 }, factAudit: {},
      serverDocumentId: "old-id", serverDocumentVersion: 3,
    };
    const phase2State = {
      expression: { results: ["旧表达"] }, academic: { outline: {}, integrity: {} },
      master_asset_id: "old-master", output_binding_hash: "old-binding", variants: [{}],
    };
    const els = {
      documentTitle: { value: "上一版" }, documentEditor: element(),
      generationHero: element(), documentWorkspace: element(), checkProgress: { textContent: "6/6" },
    };
    const globals = {
      appState, phase2State, els,
      documentPlainText: () => "旧正文",
      $$: (selector) => { assert.equal(selector, ".checklist input"); return checkboxes; },
      recipeOutline: (context) => context.headings.map((heading) => ({ heading, content: "" })),
    };
    for (const name of ["renderCandidates", "renderOutline", "renderExpressionResults", "renderVariants", "resetReviewView", "renderAcademicOutline", "renderAcademicIntegrity", "updateProjectWorkflowStatus", "renderDocumentContextStatus"]) globals[name] = () => {};
    const ui = loadHandlers(["clearTaskDerivedOutputs"], globals);
    ui.clearTaskDerivedOutputs({ headings: ["新任务范围", "新任务证据"] }, { discardDraft });
    assert.deepEqual(Array.from(appState.checklist), Array(6).fill(false));
    assert.ok(checkboxes.every((checkbox) => checkbox.checked === false));
    assert.equal(els.checkProgress.textContent, "0/6");
    assert.equal(appState.form.materials, "已保存的原始材料");
    assert.equal(phase2State.document_stale, !discardDraft);
    assert.equal(phase2State.master_asset_id, "");
    assert.equal(phase2State.output_binding_hash, "");
    assert.equal(phase2State.expression.results.length, 0);
    assert.equal(appState.review, null);
    if (!discardDraft) assert.equal(appState.document.html, "<p>旧正文</p>");
    else assert.equal(appState.document.html, "");
  }
});

test("scene controls expose only relevant evidence sources and refresh labels on every switch", () => {
  const els = new Proxy({}, { get(target, key) { return target[key] || (target[key] = element()); } });
  const checklist = Array.from({ length: 6 }, element);
  const ui = loadHandlers(["renderScenarioControls"], {
    els, scenarioCatalog: catalog,
    document: {
      createElement: () => element(),
      getElementById: (id) => checklist[Number(id.replace("checklistLabel", ""))],
    },
    makeOption: (value, label) => ({ value, label }),
    handleFormInput: () => {}, updateReferenceStyleDescription: () => {},
  });
  for (const id of ["gongwen", "workplace", "media", "academic", "workplace", "gongwen"]) {
    const scene = catalog.profiles[id];
    ui.renderScenarioControls(scene);
    assert.equal(els.appShell.dataset.scenario, id);
    assert.equal(els.selectedReferences.hidden, id !== "gongwen");
    assert.equal(els.openAcademicReferencesButton.hidden, true);
    assert.equal(els.openArticleLibraryButton.textContent, scene.source.action_label);
    assert.equal(els.referencePickerTitle.textContent, scene.source.title);
    assert.equal(els.sceneEvidenceNote.hidden, false);
    assert.match(els.sceneEvidenceNote.textContent, id === "academic" ? /文献元数据不是原文证据/ : /换场景会暂存当前输入/);
    assert.equal(els.academicIntegrityResult.hidden, id !== "academic");
    assert.deepEqual(checklist.map((label) => label.textContent), scene.checklist);
    assert.deepEqual([els.hubFormatLabel, els.hubStructureLabel, els.hubFactLabel, els.hubLanguageLabel].map((label) => label.textContent), scene.review_dimensions);
    if (id === "workplace") assert.equal(els.openArticleLibraryButton.textContent, "管理业务材料");
    if (id === "academic") assert.equal(els.openArticleLibraryButton.textContent, "打开学术文献与证据");
  }
});
