"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../gongwen_web/static/app.js"), "utf8");

// Exercise the production UI handlers with small, deterministic browser stubs.
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

function element() {
  const classes = new Map();
  return { textContent: "", classList: { toggle: (key, value) => classes.set(key, value) }, classes };
}

test("standalone documents retain the stale warning after changing their writing task", () => {
  const phase2State = { project_id: "", standalone_document: true, document_stale: true };
  const els = {
    projectWorkflowStatus: element(),
    documentContextStatus: element(),
    documentWorkspace: element(),
  };
  const ui = loadHandlers(["updateProjectWorkflowStatus", "renderDocumentContextStatus"], {
    phase2State, els, documentPlainText: () => "上一版的工作总结正文",
  });
  ui.updateProjectWorkflowStatus();
  ui.renderDocumentContextStatus();
  assert.equal(els.documentContextStatus.textContent, "上一版草稿 · 待重生成");
  assert.match(els.projectWorkflowStatus.textContent, /上一版草稿供对照/);
  assert.equal(els.documentWorkspace.classes.get("has-stale-context"), true);
  phase2State.document_stale = false;
  ui.renderDocumentContextStatus();
  assert.equal(els.documentContextStatus.textContent, "独立文稿 · 未关联项目");
});

test("an old draft is stopped before saving a revision or creating a new project asset", async () => {
  for (const existingAsset of ["", "server-asset", "local-asset"]) {
    let writes = 0;
    const phase2State = { document_stale: false, master_asset_id: existingAsset };
    const ui = loadHandlers(["ensureMasterAsset"], {
      phase2State,
      projectSwitchSerial: 0,
      requireActiveProject: () => "project-a",
      invalidateSavedBriefBinding: () => { phase2State.document_stale = true; },
      prepareServerBrief: () => { writes += 1; },
      saveMasterRevisionToServer: () => { writes += 1; },
    });
    await assert.rejects(ui.ensureMasterAsset(), (error) => error.name === "StaleDocumentError");
    assert.equal(writes, 0);
  }
});

test("a current master still saves its revision normally", async () => {
  const writes = [];
  const phase2State = { document_stale: false, master_asset_id: "asset-a" };
  const ui = loadHandlers(["ensureMasterAsset"], {
    phase2State,
    projectSwitchSerial: 0,
    requireActiveProject: () => "project-a",
    invalidateSavedBriefBinding: () => {},
    isLocalProject: () => false,
    saveMasterRevisionToServer: async (...args) => writes.push(args),
  });
  const master = await ui.ensureMasterAsset();
  assert.equal(master.id, "asset-a");
  assert.deepEqual(writes, [["project-a", "asset-a"]]);
});

test("saving an edited draft creates its asset without an extra paid generation", async () => {
  const requests = [];
  const phase2State = {
    document_stale: false, master_asset_id: "",
    brief: { id: "brief-a", payload_hash: "current" },
  };
  const ui = loadHandlers(["ensureMasterAsset"], {
    phase2State,
    els: { documentTitle: { value: "当前稿件" }, topic: { value: "当前主题" } },
    projectSwitchSerial: 0,
    requireActiveProject: () => "project-a",
    invalidateSavedBriefBinding: () => {},
    isLocalProject: () => false,
    prepareServerBrief: async () => ({ payloadHash: "current" }),
    captureInputOperation: () => ({}), inputOperationIsStale: () => false,
    workspaceContext: { assetMatchesBinding: () => true },
    progressiveV2: async (path, options) => {
      requests.push({ path, options });
      return { source: "server", data: { asset: { id: "asset-a", current_revision: 1 } } };
    },
    documentPlainText: () => "当前正文",
    saveMasterRevisionToServer: async () => {},
  });
  await ui.ensureMasterAsset();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.body.live, false);
  assert.equal(requests[0].options.body.brief_id, "brief-a");
});

test("project export and review stop before local continuation for a stale draft", async () => {
  for (const name of ["exportProjectAsset", "runProjectReview"]) {
    let continuations = 0;
    const notices = [];
    const ui = loadHandlers([name], {
      phase2State: { local_draft_mode: true },
      els: { deliveryWordButton: element(), deliveryWordSecondaryButton: element(), hubRunReviewButton: element() },
      projectSwitchSerial: 0,
      documentPlainText: () => "旧工作总结",
      requireActiveProject: () => "project-a",
      captureInputOperation: () => ({}),
      projectOperationIsStale: () => false,
      setButtonBusy: () => {},
      toast: (message) => notices.push(message),
      ensureMasterAsset: async () => {
        const error = new Error("请先重新生成当前任务正文");
        error.name = "StaleDocumentError";
        throw error;
      },
      exportDocx: async () => { continuations += 1; return true; },
      runReview: async () => { continuations += 1; return true; },
    });
    await ui[name]();
    assert.equal(continuations, 0);
    assert.deepEqual(notices, ["请先重新生成当前任务正文"]);
  }
});

function expressionHarness() {
  const pending = [];
  const phase2State = { expression: { focus: "title", count: 5, instruction: "", results: [] } };
  const els = { topic: { value: "主题甲" }, academicTitle: { value: "" }, generateExpressionsButton: element() };
  const runtime = { projectId: "project-a", model: "demo" };
  const signature = () => JSON.stringify([runtime.projectId, runtime.model, phase2State.expression.focus, els.topic.value]);
  const busy = [];
  const globals = {
    phase2State, els, projectSwitchSerial: 0, expressionRequestSerial: 0,
    syncPhase2StateFromUI: () => {}, validateServerBrief: () => {},
    serverGenerationBriefPayload: () => ({ constraints: [] }),
    requireActiveProject: () => runtime.projectId,
    captureInputOperation: () => ({ inputHash: signature() }),
    inputOperationIsStale: (operation, error) => error?.name === "AbortError" || operation.inputHash !== signature(),
    projectOperationIsStale: (projectId) => projectId !== runtime.projectId,
    setButtonBusy: (_, value) => busy.push(value),
    progressiveV2: () => new Promise((resolve) => pending.push(resolve)),
    normalizeExpressionCandidates: (data) => data.items,
    renderExpressionResults: () => {}, persistPhase2State: () => {}, toast: () => {},
    readError: (error) => error.message,
  };
  return { ...loadHandlers(["generateExpressions"], globals), phase2State, els, runtime, pending, busy };
}

test("delayed expression candidates are discarded after focus, topic, mode or project changes", async () => {
  for (const mutate of [
    (ui) => { ui.phase2State.expression.focus = "topic_sentence"; },
    (ui) => { ui.els.topic.value = "主题乙"; },
    (ui) => { ui.runtime.model = "api"; },
    (ui) => { ui.runtime.projectId = "project-b"; },
  ]) {
    const ui = expressionHarness();
    const request = ui.generateExpressions();
    mutate(ui);
    ui.pending[0]({ source: "server", data: { items: ["主题甲的标题"] } });
    await request;
    assert.deepEqual(ui.phase2State.expression.results, []);
  }
});

test("newer expression requests win even with identical inputs", async () => {
  const ui = expressionHarness();
  const first = ui.generateExpressions();
  const second = ui.generateExpressions();
  ui.pending[1]({ source: "server", data: { items: ["新候选"] } });
  await second;
  ui.pending[0]({ source: "server", data: { items: ["旧候选"] } });
  await first;
  assert.deepEqual(ui.phase2State.expression.results, ["新候选"]);
  assert.deepEqual(ui.busy, [true, true, false]);
});
