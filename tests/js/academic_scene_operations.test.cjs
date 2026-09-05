"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const workspaceContext = require("../../gongwen_web/static/workspace_context.js");

const source = fs.readFileSync(path.join(__dirname, "../../gongwen_web/static/app.js"), "utf8");

function handler(name) {
  const start = source.search(new RegExp(`^  (?:async )?function ${name}\\(`, "m"));
  assert.ok(start >= 0, `missing handler: ${name}`);
  const rest = source.slice(start + 1);
  const next = rest.search(/^  (?:async )?function /m);
  return source.slice(start, next < 0 ? source.lastIndexOf("})();") : start + 1 + next);
}

function loadHandlers(names, globals) {
  return vm.runInNewContext(`${names.map(handler).join("\n")}\n({${names.join(",")}})`, globals);
}

const actions = [
  "importAcademicRecords", "generateAcademicMatrix", "extractAcademicEvidence",
  "formatAcademicCitations", "generateAcademicOutline", "generateAcademicRebuttal",
  "verifyAcademicClaims",
];

function academicHarness() {
  const pending = [];
  const notices = [];
  const busy = [];
  const runtime = { projectId: "project-a", serial: 1, revision: 1, writes: 0 };
  const record = { id: "r1", title: "A real fixture record", source_hash: "source-r1", _server_synced: true };
  const phase2State = {
    project_id: "project-a", brief: { scenario_pack_id: "academic" },
    academic: { records: [record], evidence: [{ id: "e1", record_id: "r1", content_hash: "e1-hash" }],
      title: "研究主题", task_type: "research-outline", matrix: [], citations: [], outline: null, rebuttal: [],
      claim_links: [], claim_comments: [], claims: [], coverage: null, integrity: null },
  };
  const els = {};
  for (const name of [
    "academicImportContent", "academicImportFormat", "academicEvidenceRecord", "academicEvidenceQuery",
    "academicEvidenceText", "academicCitationStyle", "academicTitle", "academicReviewerComments",
    "academicManuscriptChanges", "academicImportButton", "academicMatrixButton", "academicExtractEvidenceButton",
    "academicFormatCitationsButton", "academicOutlineButton", "academicRebuttalButton", "academicVerifyClaimsButton",
  ]) els[name] = { name, value: "fixture", focus: () => {} };
  els.academicEvidenceRecord.value = "r1";
  const signature = () => JSON.stringify([runtime.projectId, runtime.serial, runtime.revision,
    phase2State.brief.scenario_pack_id, phase2State.academic.title,
    phase2State.academic.records, phase2State.academic.evidence]);
  const request = (url, options) => new Promise((resolve, reject) => pending.push({ resolve, reject, url, options }));
  const globals = {
    phase2State, els, MAX_ACADEMIC_RECORDS: 1000, MAX_ACADEMIC_EVIDENCE: 1000,
    academicOperationSerials: new Map(),
    requireActiveProject: () => runtime.projectId,
    captureInputOperation: () => ({ projectId: runtime.projectId, projectSerial: runtime.serial, inputHash: signature() }),
    inputOperationIsStale: (operation, error) => error?.name === "AbortError" || operation.inputHash !== signature(),
    projectOperationIsStale: (projectId, serial) => projectId !== runtime.projectId || serial !== runtime.serial,
    setButtonBusy: (button, state) => busy.push([button.name, state]),
    progressiveV2: request, progressiveAcademicV2: request,
    normalizeAcademicRecords: (records) => records,
    parseAcademicRecordsLocally: () => [{ id: "r2", title: "Imported fixture", source_hash: "source-r2" }],
    bibliographicIdentity: (item) => item.source_hash || item.id,
    academicEvidenceSelection: () => ({ record_ids: ["r1"], evidence_ids: ["e1"] }),
    academicClaims: () => [{ id: "claim-1", text: "fixture claim" }],
    academicCandidateLinks: () => [], academicBriefPayload: () => ({ record_ids: ["r1"] }),
    localAcademicOutline: () => ({}),
    normalizeEvidenceSnippets: (items) => items, validAcademicLinks: (links) => links,
    normalizeClaimComments: (comments) => comments,
    isCanonicalAcademicMatrix: () => true, isCanonicalAcademicOutline: () => true,
    isCanonicalAcademicAbstract: () => true, isCanonicalCitationAudit: () => true,
    syncPhase2StateFromUI: () => {}, simpleHash: (text) => text,
    persistPhase2State: () => { runtime.writes += 1; },
    toast: (message, level) => notices.push([message, level]), readError: (error) => error.message,
  };
  for (const name of ["renderAcademicRecords", "renderAcademicMatrix", "renderAcademicClaimLinks",
    "renderAcademicCitations", "renderAcademicOutline", "renderAcademicIntegrity", "renderAcademicEvidence",
    "renderAcademicRebuttal"]) globals[name] = () => {};
  const ui = loadHandlers([
    "academicOperationFields", "captureAcademicOperation", "academicOperationIsStale", "finishAcademicOperation",
    "splitReviewerComments", "selectedAcademicTask", ...actions,
  ], globals);
  return { ...ui, phase2State, els, runtime, pending, notices, busy };
}

const responses = {
  importAcademicRecords: { records: [{ id: "r2", title: "Imported fixture", source_hash: "source-r2" }] },
  generateAcademicMatrix: { matrix: { id: "matrix-1", rows: [{ record_id: "r1", findings: ["fixture finding"] }] } },
  extractAcademicEvidence: { snippets: [{ id: "e2", record_id: "r1", record_source_hash: "source-r1", text: "fixture original text" }] },
  formatAcademicCitations: { count: 1, items: [{ record_id: "r1", text: "Fixture reference, 2026." }] },
  generateAcademicOutline: { outline: { title: "研究主题", sections: [{ heading: "问题与方法", guidance: "fixture guidance" }] } },
  generateAcademicRebuttal: { items: [{ response: "Fixture reply", change_location: "p. 2" }] },
  verifyAcademicClaims: { citation_audit: { links: [], comments: [], coverage: 0 } },
};

for (const action of actions) {
  test(`${action}: delayed success never writes into a changed scene, task or project`, async () => {
    for (const mutate of [
      (ui) => { ui.phase2State.brief.scenario_pack_id = "workplace"; },
      (ui) => { ui.phase2State.academic.title = "另一研究问题"; },
      (ui) => { ui.runtime.projectId = "project-b"; ui.runtime.serial += 1; },
    ]) {
      const ui = academicHarness();
      const request = ui[action]();
      assert.equal(ui.pending.length, 1, `${action} must reach its service request`);
      mutate(ui);
      const expected = JSON.stringify(ui.phase2State.academic);
      ui.pending[0].resolve({ source: "server", data: responses[action] });
      await request;
      assert.equal(JSON.stringify(ui.phase2State.academic), expected);
      assert.equal(ui.runtime.writes, 0);
      assert.deepEqual(ui.notices, []);
    }
  });

  test(`${action}: a current response still writes successfully`, async () => {
    const ui = academicHarness();
    const request = ui[action]();
    ui.pending[0].resolve({ source: "server", data: responses[action] });
    await request;
    assert.equal(ui.runtime.writes, 1, JSON.stringify(ui.notices));
    assert.equal(ui.notices.at(-1)?.[1], "success");
    assert.equal(ui.busy.at(-1)?.[1], false);
  });
}

test("changing pasted import content or evidence selection discards the pending result", async () => {
  for (const [action, field] of [
    ["importAcademicRecords", "academicImportContent"], ["importAcademicRecords", "academicImportFormat"],
    ["extractAcademicEvidence", "academicEvidenceRecord"], ["extractAcademicEvidence", "academicEvidenceText"],
    ["extractAcademicEvidence", "academicEvidenceQuery"],
  ]) {
    const ui = academicHarness();
    const request = ui[action]();
    ui.els[field].value = "changed input";
    ui.pending[0].resolve({ source: "server", data: responses[action] });
    await request;
    assert.equal(ui.runtime.writes, 0);
    assert.deepEqual(ui.notices, []);
    assert.equal(ui.busy.at(-1)?.[1], false);
  }
});

test("newest academic request wins even when repeated inputs are identical", async () => {
  for (const action of actions) {
    const ui = academicHarness();
    const first = ui[action]();
    const second = ui[action]();
    ui.pending[0].resolve({ source: "server", data: responses[action] });
    await first;
    assert.equal(ui.runtime.writes, 0);
    assert.equal(ui.busy.at(-1)?.[1], true, "old completion must not unlock a newer request");
    ui.pending[1].resolve({ source: "server", data: responses[action] });
    await second;
    assert.equal(ui.runtime.writes, 1, action);
  }
});

test("stale academic failures do not overwrite the latest page status", async () => {
  for (const action of actions) {
    const ui = academicHarness();
    const request = ui[action]();
    ui.phase2State.brief.scenario_pack_id = "media";
    ui.pending[0].reject(new Error("an old service failed"));
    await request;
    assert.deepEqual(ui.notices, []);
    assert.equal(ui.runtime.writes, 0);
  }
});

test("each research task sends its own document type and uses the appropriate service", async () => {
  for (const [task, documentType, endpoint] of [
    ["literature-review", "文献综述", "/outline"],
    ["research-outline", "研究提纲", "/outline"],
    ["abstract", "摘要", "/abstract"],
    ["rebuttal", null, "/rebuttal"],
  ]) {
    const ui = academicHarness();
    ui.phase2State.academic.task_type = task;
    const request = ui.generateAcademicOutline();
    assert.equal(ui.pending.length, 1);
    assert.ok(ui.pending[0].url.endsWith(endpoint), task);
    if (documentType) assert.equal(ui.pending[0].options.body.document_type, documentType);
    const data = task === "abstract"
      ? { abstract: { text: "摘要内容", record_ids: ["r1"], claim_ids: [], placeholders: [] } }
      : task === "rebuttal" ? responses.generateAcademicRebuttal : responses.generateAcademicOutline;
    ui.pending[0].resolve({ source: "server", data });
    await request;
    if (task !== "rebuttal") assert.equal(ui.phase2State.academic.outline.task_type, task);
    else assert.equal(ui.phase2State.academic.outline, null);
  }
});

test("local literature review and research plans use the same four-section recipes as the workspace", () => {
  const phase2State = { academic: { title: "研究任务", records: [], evidence: [], task_type: "literature-review" } };
  const ui = loadHandlers(["selectedAcademicTask", "localAcademicOutline"], {
    phase2State, els: {}, workspaceContext, uniqueAcademicThemes: () => [],
  });
  for (const [task, recipeId] of [["literature-review", "literature-review"], ["research-outline", "research-outline"]]) {
    phase2State.academic.task_type = task;
    const outline = ui.localAcademicOutline();
    const expected = workspaceContext.findRecipe("academic", recipeId)[4].methodology.headings;
    assert.deepEqual(Array.from(outline.sections, (section) => section.heading), Array.from(expected));
    assert.equal(outline.task_type, task);
    assert.equal(outline.sections.length, 4);
  }
});

function node(tag = "div") {
  const classes = new Set();
  const result = {
    tag, textContent: "", value: "", children: [], disabled: false, listeners: {},
    classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name), toggle: () => {} },
    append(...items) { for (const item of items) this.children.push(...(item.tag === "fragment" ? item.children : [item])); },
    replaceChildren(...items) { this.children = []; this.append(...items); },
    addEventListener(name, listener) { this.listeners[name] = listener; },
  };
  return result;
}

function insertionHarness() {
  const outline = { title: "研究问题", sections: [{ heading: "问题与范围", guidance: "检查原文与证据" }] };
  const citations = [{ record_id: "r1", text: "[1] Fixture reference." }];
  const phase2State = { project_id: "project-a", brief: { scenario_pack_id: "academic" }, document_stale: false,
    academic: { title: "研究问题", outline, citations } };
  const original = node("p"); original.textContent = "Existing manuscript paragraph.";
  const els = { documentEditor: node(), documentTitle: node("input"), topic: node("input"), generationHero: node(),
    documentWorkspace: node(), academicOutline: node(), academicCitationOutput: node() };
  els.documentEditor.append(original); els.documentTitle.value = "Existing title";
  const appState = { document: { execution: { mode: "live", model: "fixture-model" } } };
  const runtime = { edited: 0, activated: [], focus: [], notices: [] };
  const globals = {
    phase2State, els, appState,
    document: { createElement: node, createDocumentFragment: () => node("fragment") },
    documentPlainText: () => els.documentEditor.children.map((item) => item.textContent).join("\n"),
    activateScenario: (pack) => { runtime.activated.push(pack); phase2State.brief.scenario_pack_id = pack; },
    toast: (message) => runtime.notices.push(message),
    focusProjectControl: (id) => runtime.focus.push(id),
    handleDocumentInput: () => { runtime.edited += 1; }, renderDocumentExecution: () => {},
    normalizeGeneratedPunctuation: (value) => value,
    copyPlainText: () => {},
  };
  const ui = loadHandlers(["academicContentBlocks", "appendAcademicContent", "renderAcademicCitations",
    "renderAcademicOutline", "appendAcademicOutlineAction"], globals);
  return { ...ui, phase2State, els, appState, runtime, original, outline, citations };
}

test("adopting research results appends without overwriting the manuscript or inventing model provenance", () => {
  const ui = insertionHarness();
  const execution = ui.appState.document.execution;
  assert.equal(ui.appendAcademicContent("outline", ui.outline, "project-a"), true);
  assert.equal(ui.els.documentEditor.children[0], ui.original);
  assert.equal(ui.els.documentTitle.value, "Existing title");
  assert.equal(ui.appState.document.execution, execution);
  assert.deepEqual(ui.els.documentEditor.children.slice(1).map((item) => item.textContent), ["研究提纲（待完善）", "问题与范围", "检查原文与证据"]);
  assert.equal(ui.runtime.edited, 1);
  assert.deepEqual(ui.runtime.focus, ["documentEditor"]);
});

test("adopting references appends the bibliography to the current manuscript", () => {
  const ui = insertionHarness();
  assert.equal(ui.appendAcademicContent("citations", ui.citations, "project-a"), true);
  assert.equal(ui.els.documentEditor.children[0], ui.original);
  assert.deepEqual(ui.els.documentEditor.children.slice(1).map((item) => item.textContent), ["参考文献", "[1] Fixture reference."]);
});

test("an empty manuscript created from academic tools is not labelled as model generated", () => {
  const ui = insertionHarness();
  ui.els.documentEditor.replaceChildren(); ui.els.documentTitle.value = "";
  assert.equal(ui.appendAcademicContent("outline", ui.outline, "project-a"), true);
  assert.equal(ui.appState.document.execution, null);
  assert.equal(ui.els.documentTitle.value, "研究问题");
});

test("outdated drafts, old results and other projects reject academic insertion without changing the manuscript", () => {
  for (const mutate of [
    (ui) => { ui.phase2State.document_stale = true; },
    (ui) => { ui.phase2State.project_id = "project-b"; },
    (ui) => { ui.phase2State.academic.outline = { title: "New result" }; },
  ]) {
    const ui = insertionHarness(); mutate(ui);
    assert.equal(ui.appendAcademicContent("outline", ui.outline, "project-a"), false);
    assert.deepEqual(ui.els.documentEditor.children, [ui.original]);
    assert.equal(ui.runtime.edited, 0);
  }
});

test("cross-scene insertion activates academic only after the user's click and leaves the old manuscript alone", () => {
  const ui = insertionHarness();
  ui.phase2State.brief.scenario_pack_id = "workplace";
  ui.renderAcademicOutline();
  assert.deepEqual(ui.runtime.activated, []);
  const button = ui.els.academicOutline.children.find((item) => item.tag === "button");
  button.listeners.click();
  assert.deepEqual(ui.runtime.activated, ["academic"]);
  assert.deepEqual(ui.els.documentEditor.children, [ui.original]);
  assert.equal(ui.runtime.edited, 0);
});

test("outline and bibliography cards expose explicit adoption actions and prevent accidental repeated clicks", () => {
  for (const [render, container, label] of [
    ["renderAcademicOutline", "academicOutline", "放入当前母稿"],
    ["renderAcademicCitations", "academicCitationOutput", "追加参考文献"],
  ]) {
    const ui = insertionHarness(); ui[render]();
    const button = ui.els[container].children.find((item) => item.tag === "button" && item.textContent === label);
    assert.ok(button, label);
    assert.equal(ui.runtime.edited, 0);
    button.listeners.click();
    assert.equal(ui.runtime.edited, 1);
    assert.equal(button.disabled, true);
  }
});
