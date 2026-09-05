(function exposeExecutionMode(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.YanzhangExecutionMode = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createExecutionMode() {
  "use strict";

  const LOCAL_LABEL = "模板演示 · 未调用大模型";
  const LOCAL_DETAIL = "使用内置模板、写作公式和规则评分，不消耗模型 Token；演示结果用于体验流程。";
  const normalizeProvider = (value) => ({ deepseek: "openai", qwen: "openai", custom: "openai" })[value] || value || "openai";

  function connection({ settings = {}, server = {}, keyPresent = false } = {}) {
    const client = Boolean(settings.baseUrl || settings.modelName || keyPresent);
    if (settings.mode !== "api") return { mode: "local", source: "local", ready: true, label: LOCAL_LABEL, detail: LOCAL_DETAIL, projectReady: true };
    const model = String(client ? settings.modelName || "" : server.defaultModel || "");
    const provider = normalizeProvider(client ? settings.providerName : server.providerName);
    const ready = client ? Boolean(model && keyPresent) : Boolean(server.configured && model);
    return {
      mode: "live", source: client ? "browser" : "server", model, provider, ready,
      projectReady: !client && ready,
      label: ready ? `模型 API · ${model}` : "模型 API · 待完成连接",
      detail: client
        ? `当前页面连接 · ${provider} · ${keyPresent ? "密钥仅在页面内存" : "本页尚未填写密钥"}。项目工作流使用独立的服务端配置。`
        : server.configured ? `服务端连接 · ${provider} · 点击生成后发送当前任务内容；按供应商规则计费。`
          : "服务端尚未配置模型。打开模型设置，填写接口、模型名称和本页密钥。",
    };
  }

  function execution(raw) {
    const value = raw?.execution || raw?.meta || raw;
    if (!value || typeof value !== "object") return null;
    if (value.mode === "local" || value.mode === "demo") {
      return { mode: "local", label: LOCAL_LABEL, provider: null, model: null };
    }
    if (value.mode === "live") {
      const model = String(value.model || "");
      const provider = String(value.provider || "");
      return { mode: "live", label: model ? `模型 API · ${model}${provider ? `（${provider}）` : ""}` : "模型 API · 返回结果未注明模型", provider, model };
    }
    return null;
  }

  return Object.freeze({ LOCAL_LABEL, LOCAL_DETAIL, connection, execution });
});
