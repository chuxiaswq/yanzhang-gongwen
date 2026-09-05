"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const engine = require("../../gongwen_web/static/execution_mode.js");

test("demo clearly identifies templates rather than a model even with live credentials configured", () => {
  const status = engine.connection({
    settings: { mode: "demo", providerName: "deepseek", modelName: "browser-model", baseUrl: "https://example.test/v1" },
    server: { configured: true, providerName: "server-provider", defaultModel: "server-model" },
    keyPresent: true,
  });
  assert.deepEqual(status, {
    mode: "local", source: "local", ready: true, projectReady: true,
    label: engine.LOCAL_LABEL, detail: engine.LOCAL_DETAIL,
  });
  assert.match(status.label, /未调用大模型/);
  assert.match(status.detail, /不消耗模型 Token/);
  assert.equal(Object.hasOwn(status, "model"), false);
  assert.equal(Object.hasOwn(status, "provider"), false);
});

test("the unconfigured default is the local template demo", () => {
  assert.deepEqual(engine.connection(), engine.connection({ settings: { mode: "demo" } }));
  assert.equal(engine.connection().mode, "local");
  assert.equal(engine.connection().ready, true);
});

test("server API connections show the actual default model and provider", () => {
  const status = engine.connection({
    settings: { mode: "api", providerName: "deepseek" },
    server: { configured: true, providerName: "anthropic", defaultModel: "server-model" },
  });
  assert.equal(status.mode, "live");
  assert.equal(status.source, "server");
  assert.equal(status.model, "server-model");
  assert.equal(status.provider, "anthropic");
  assert.equal(status.ready, true);
  assert.equal(status.projectReady, true);
  assert.equal(status.label, "模型 API · server-model");
  assert.match(status.detail, /服务端连接 · anthropic/);
});

test("a missing server connection or missing server model is not reported ready", () => {
  for (const server of [
    {},
    { configured: false, providerName: "openai", defaultModel: "server-model" },
    { configured: true, providerName: "openai", defaultModel: "" },
  ]) {
    const status = engine.connection({ settings: { mode: "api" }, server });
    assert.equal(status.source, "server");
    assert.equal(status.ready, false);
    assert.equal(status.projectReady, false);
    assert.equal(status.label, "模型 API · 待完成连接");
  }
});

test("browser connections require both their own model and a current page key", () => {
  const server = { configured: true, providerName: "openai", defaultModel: "server-model" };
  for (const [settings, keyPresent, expectedReady] of [
    [{ mode: "api", modelName: "browser-model" }, true, true],
    [{ mode: "api", modelName: "browser-model" }, false, false],
    [{ mode: "api", baseUrl: "https://example.test/v1" }, true, false],
    [{ mode: "api", baseUrl: "https://example.test/v1" }, false, false],
    [{ mode: "api" }, true, false],
  ]) {
    const status = engine.connection({ settings, server, keyPresent });
    assert.equal(status.source, "browser");
    assert.equal(status.ready, expectedReady);
    assert.equal(status.projectReady, false);
    assert.notEqual(status.model, "server-model", "partial browser configuration must not borrow the server identity");
    assert.match(status.detail, keyPresent ? /密钥仅在页面内存/ : /本页尚未填写密钥/);
  }
});

test("compatible browser provider aliases match the backend adapter identity", () => {
  for (const providerName of ["deepseek", "qwen", "custom", "openai", ""]) {
    const status = engine.connection({ settings: { mode: "api", providerName, modelName: "browser-model" }, keyPresent: true });
    assert.equal(status.provider, "openai");
    assert.equal(status.ready, true);
    assert.equal(status.projectReady, false);
  }
  const explicit = engine.connection({ settings: { mode: "api", providerName: "anthropic", modelName: "browser-model" }, keyPresent: true });
  assert.equal(explicit.provider, "anthropic");
});

test("execution history labels a demo as local and discards irrelevant model claims", () => {
  for (const mode of ["demo", "local"]) {
    const expected = { mode: "local", label: engine.LOCAL_LABEL, provider: null, model: null };
    const raw = { mode, provider: "unrelated-provider", model: "unrelated-model" };
    assert.deepEqual(engine.execution(raw), expected);
    assert.deepEqual(engine.execution({ execution: raw }), expected);
    assert.deepEqual(engine.execution({ meta: raw }), expected);
  }
});

test("live execution history uses the result identity rather than the current connection", () => {
  const history = { mode: "live", provider: "provider-a", model: "model-a" };
  const expected = { ...history, label: "模型 API · model-a（provider-a）" };
  assert.deepEqual(engine.execution(history), expected);
  assert.deepEqual(engine.execution({ execution: history }), expected);
  assert.deepEqual(engine.execution({ meta: history }), expected);
  assert.equal(engine.execution({ mode: "live", model: "model-a" }).label, "模型 API · model-a");
  assert.equal(engine.execution({ mode: "live" }).label, "模型 API · 返回结果未注明模型");
});

test("old or unknown execution history remains unknown instead of being inferred as live", () => {
  for (const raw of [undefined, null, "demo", 0, [], {}, { model: "model-a" }, { mode: "unknown" }, { execution: { mode: "unknown" } }, { meta: {} }]) {
    assert.equal(engine.execution(raw), null);
  }
});

test("explicit execution metadata takes precedence over older generic metadata", () => {
  const status = engine.execution({
    execution: { mode: "demo" },
    meta: { mode: "live", provider: "provider-a", model: "model-a" },
  });
  assert.equal(status.mode, "local");
  assert.equal(status.model, null);
});

test("connection and execution helpers preserve their inputs and return fresh outputs", () => {
  const input = Object.freeze({
    settings: Object.freeze({ mode: "api", providerName: "qwen", modelName: "browser-model" }),
    server: Object.freeze({ configured: true, providerName: "anthropic", defaultModel: "server-model" }),
    keyPresent: true,
  });
  const history = Object.freeze({ execution: Object.freeze({ mode: "live", model: "result-model", provider: "result-provider" }) });
  const beforeConnection = JSON.stringify(input);
  const beforeHistory = JSON.stringify(history);
  const firstConnection = engine.connection(input);
  const firstExecution = engine.execution(history);
  firstConnection.label = "changed by consumer";
  firstExecution.label = "changed by consumer";
  assert.equal(JSON.stringify(input), beforeConnection);
  assert.equal(JSON.stringify(history), beforeHistory);
  assert.equal(engine.connection(input).label, "模型 API · browser-model");
  assert.equal(engine.execution(history).label, "模型 API · result-model（result-provider）");
  assert.equal(Object.isFrozen(engine), true);
});
