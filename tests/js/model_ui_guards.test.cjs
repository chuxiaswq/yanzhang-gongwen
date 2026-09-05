"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const executionMode = require("../../gongwen_web/static/execution_mode.js");

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

function connectionHarness({ settings = {}, serverProvider = {}, sessionApiKey = "", extras = {} } = {}) {
  const notices = [];
  const opened = [];
  const globals = {
    settings, serverProvider, sessionApiKey, executionMode,
    openSettings: () => opened.push(true), toast: (...args) => notices.push(args),
    ...extras,
  };
  const names = ["currentModelConnection", "requireModelConnection"];
  return { globals, names, notices, opened, ...loadHandlers(names, globals) };
}

test("demo mode allows both single-document and project work without a model", () => {
  const ui = connectionHarness({ settings: { mode: "demo" } });
  assert.equal(ui.requireModelConnection(), true);
  assert.equal(ui.requireModelConnection({ project: true }), true);
  assert.equal(ui.opened.length, 0);
  assert.equal(ui.notices.length, 0);
});

test("an incomplete API connection opens settings and stops the action", () => {
  for (const settings of [{ mode: "api" }, { mode: "api", modelName: "page-model" }]) {
    const ui = connectionHarness({ settings });
    assert.equal(ui.requireModelConnection(), false);
    assert.equal(ui.opened.length, 1);
    assert.equal(ui.notices[0][1], "warning");
    assert.match(ui.notices[0][0], /连接尚未完成/);
  }
});

test("a browser override permits single writing but not project model workflows", () => {
  const ui = connectionHarness({
    settings: { mode: "api", providerName: "openai", modelName: "page-model" },
    serverProvider: { configured: true, providerName: "openai", defaultModel: "server-model" },
    sessionApiKey: "fixture-key",
  });
  assert.equal(ui.requireModelConnection(), true);
  assert.equal(ui.requireModelConnection({ project: true }), false);
  assert.equal(ui.opened.length, 1);
  assert.match(ui.notices[0][0], /页面临时连接/);
});

test("a complete server connection permits both kinds of writing", () => {
  const ui = connectionHarness({
    settings: { mode: "api" },
    serverProvider: { configured: true, providerName: "openai", defaultModel: "server-model" },
  });
  assert.equal(ui.requireModelConnection(), true);
  assert.equal(ui.requireModelConnection({ project: true }), true);
  assert.equal(ui.opened.length, 0);
});

function progressiveHarness(error, localDraftMode = true) {
  const fallbackCalls = [];
  const states = [];
  const ui = loadHandlers(["progressiveV2"], {
    phase2State: { local_draft_mode: localDraftMode },
    apiRequest: async () => { throw error; },
    setV2ServiceState: (state) => states.push(state),
  });
  return {
    ...ui, states, fallbackCalls,
    local: async (received) => { fallbackCalls.push(received); return { preview: true }; },
  };
}

test("a requested live model operation never becomes a local preview after a service error", async () => {
  for (const status of [0, 404, 500, 503]) {
    const error = Object.assign(new Error("fixture service error"), { status });
    const ui = progressiveHarness(error);
    await assert.rejects(ui.progressiveV2("/fixture", { body: { live: true } }, ui.local), (received) => received === error);
    assert.equal(ui.fallbackCalls.length, 0);
    assert.deepEqual(ui.states, []);
  }
});

test("explicit local drafts can continue as visibly local previews for demo requests", async () => {
  for (const body of [{ live: false }, {}]) {
    const error = Object.assign(new Error("fixture service error"), { status: 503 });
    const ui = progressiveHarness(error);
    const result = await ui.progressiveV2("/fixture", { body }, ui.local);
    assert.equal(result.source, "local");
    assert.equal(result.data.preview, true);
    assert.equal(result.error, error);
    assert.deepEqual(ui.fallbackCalls, [error]);
    assert.deepEqual(ui.states, ["local"]);
  }
});

test("disabled local drafts and non-retriable errors do not create preview output", async () => {
  for (const [status, localDraftMode] of [[503, false], [400, true], [401, true], [409, true]]) {
    const error = Object.assign(new Error("fixture service error"), { status });
    const ui = progressiveHarness(error, localDraftMode);
    await assert.rejects(ui.progressiveV2("/fixture", { body: { live: false } }, ui.local), (received) => received === error);
    assert.equal(ui.fallbackCalls.length, 0);
  }
});

test("aborted requests propagate directly even for a demo", async () => {
  const error = Object.assign(new Error("fixture abort"), { name: "AbortError" });
  const ui = progressiveHarness(error);
  await assert.rejects(ui.progressiveV2("/fixture", { body: { live: false } }, ui.local), (received) => received === error);
  assert.equal(ui.fallbackCalls.length, 0);
  assert.deepEqual(ui.states, []);
});

test("successful live requests preserve server output and never call the local generator", async () => {
  const data = { text: "server output", execution: { mode: "live", model: "server-model" } };
  const options = Object.freeze({ method: "POST", body: Object.freeze({ live: true }) });
  const requests = [];
  const states = [];
  const ui = loadHandlers(["progressiveV2"], {
    apiRequest: async (...args) => { requests.push(args); return data; },
    setV2ServiceState: (state) => states.push(state),
  });
  const result = await ui.progressiveV2("/fixture", options, () => assert.fail("unexpected local generation"));
  assert.equal(result.source, "server");
  assert.equal(result.data, data);
  assert.equal(requests[0][1], options);
  assert.deepEqual(states, ["connected"]);
});

test("review and selection rewrite stop at the connection guard before reading or submitting content", async () => {
  for (const name of ["runReview", "rewriteSelection"]) {
    let requests = 0;
    let contentReads = 0;
    const ui = connectionHarness({
      settings: { mode: "api" },
      extras: {
        apiRequest: async () => { requests += 1; },
        documentPlainText: () => { contentReads += 1; return "fixture document"; },
        savedSelection: { toString: () => { contentReads += 1; return "fixture selection"; } },
      },
    });
    const actions = loadHandlers([...ui.names, name], ui.globals);
    const result = await actions[name]("polish");
    if (name === "runReview") assert.equal(result, false);
    assert.equal(requests, 0);
    assert.equal(contentReads, 0);
    assert.equal(ui.opened.length, 1);
  }
});

test("document source labels use the stored execution rather than current model settings", () => {
  for (const [execution, mode, expected] of [
    [{ mode: "local" }, "api", "未调用大模型"],
    [{ mode: "live", model: "actual-old-model", provider: "actual-provider" }, "demo", "actual-old-model（actual-provider）"],
    [null, "api", "未记录（历史稿或手工内容）"],
  ]) {
    const els = { documentExecution: { textContent: "" } };
    const appState = { document: { execution } };
    const before = JSON.stringify(appState);
    const ui = loadHandlers(["renderDocumentExecution"], {
      appState, els, executionMode, settings: { mode, modelName: "new-current-model" },
      currentModelConnection: () => assert.fail("historical source must not depend on current settings"),
    });
    ui.renderDocumentExecution();
    assert.ok(els.documentExecution.textContent.includes(expected));
    assert.equal(els.documentExecution.textContent.includes("new-current-model"), false);
    assert.equal(JSON.stringify(appState), before);
  }
});

test("bootstrap preserves academic and custom document types omitted from the legacy catalog", async () => {
  for (const selectedDocumentType of ["文献综述", "研究提纲", "自定义学术稿"]) {
    const appState = { form: { document_type: selectedDocumentType } };
    const documentType = {
      value: selectedDocumentType,
      options: [{ value: selectedDocumentType }],
      append(option) { this.options.push(option); },
    };
    const reconciled = [];
    const connections = [];
    const ui = loadHandlers(["bootstrap", "ensureDocumentTypeOption"], {
      appState, els: { documentType },
      apiRequest: async () => ({ document_types: ["通知", "请示", "工作总结"], model: {} }),
      configurePeopleSearch: () => {}, updateDeploymentStatus: () => {},
      replaceOptions: (select, values) => {
        select.options = values.map((value) => ({ value }));
        select.value = select.options[0].value;
      },
      makeOption: (value, label) => ({ value, label }),
      reconcileTaskContext: () => { reconciled.push(documentType.value); appState.form.document_type = documentType.value; },
      loadMethodologyCatalog: async () => {}, setConnection: (value) => connections.push(value),
      methodologyCatalogReady: true,
      console: { info: () => assert.fail("bootstrap unexpectedly failed") },
    });
    assert.equal(await ui.bootstrap(), true);
    assert.equal(documentType.value, selectedDocumentType);
    assert.equal(appState.form.document_type, selectedDocumentType);
    assert.ok(documentType.options.some((option) => option.value === selectedDocumentType));
    assert.deepEqual(reconciled, [selectedDocumentType]);
    assert.deepEqual(connections, [true]);
  }
});

test("connection tests reject partial browser credentials even when a server model exists", async () => {
  for (const provider of [
    { model: "page-model" },
    { api_key: "fixture-key" },
    { base_url: "https://example.test/v1" },
  ]) {
    const requests = [];
    const focus = [];
    const notices = [];
    const ui = loadHandlers(["testProviderConnection"], {
      providerTestSerial: 0,
      serverProvider: { configured: true, defaultModel: "server-model" },
      providerPayloadFromForm: () => provider,
      els: { modelName: { focus: () => focus.push("model") }, apiKey: { focus: () => focus.push("key") } },
      apiRequest: async (...args) => requests.push(args),
      toast: (message) => notices.push(message),
    });
    await ui.testProviderConnection();
    assert.equal(requests.length, 0);
    assert.deepEqual(focus, [provider.model ? "key" : "model"]);
    assert.match(notices[0], /同时填写模型名称和本页密钥/);
  }
});
