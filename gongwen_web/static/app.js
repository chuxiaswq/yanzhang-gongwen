(() => {
  "use strict";

  const STORAGE_KEY = "yanzhang.demo.document.v1";
  const SETTINGS_KEY = "yanzhang.demo.settings.v1";
  const HISTORY_KEY = "yanzhang.demo.history.v1";
  const ACCESS_TOKEN_KEY = "yanzhang.access-token.v1";
  const MAX_HISTORY = 12;

  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];

  const els = {};
  let appState = freshState();
  let settings = { mode: "demo", providerName: "openai", baseUrl: "", modelName: "" };
  let sessionApiKey = "";
  let sessionAccessToken = "";
  let accessTokenRequired = false;
  let serverProvider = { configured: false, providerName: "", defaultModel: "" };
  let savedSelection = null;
  let saveTimer = 0;
  let factTimer = 0;
  let catalogRequestSerial = 0;
  let methodologyCatalog = { titleFormulas: [], contentMethodologies: [], defaults: [] };

  const EXAMPLE = {
    document_type: "工作总结",
    topic: "2026年上半年数字化转型",
    purpose: "系统总结阶段性成效，分析问题并部署下一步工作",
    audience: "各处室、各直属单位",
    tone: "严谨规范",
    reference_style: "权威媒体综合写法",
    length: "标准",
    requirements: "突出数据成效，问题分析客观，下一步任务写明时间节点。",
    materials:
      "截至2026年6月30日，统一事项平台已接入18个处室，累计流转事项12,604件，平均办理时长较去年同期下降31%。完成6个业务系统整合，清理重复账号241个；开展业务培训8场，覆盖420人次。目前仍存在数据标准不统一、基层重复填报等问题。下一步计划于9月底前完成数据目录，于10月启动移动审批试点。",
  };

  document.addEventListener("DOMContentLoaded", init);

  function freshState() {
    return {
      form: {
        document_type: "实施方案", topic: "", purpose: "", audience: "", tone: "严谨规范",
        reference_style: "权威媒体综合写法", length: "标准", requirements: "", materials: "", factLock: true,
        content_methodology_id: "", custom_methodology: null, title_formula_ids: [], title_count: 5,
        custom_title_formula: null,
      },
      document: { title: "", html: "", candidates: [], outline: [] },
      review: null,
      factAudit: null,
      styleReferences: [],
      serverDocumentId: "",
      serverDocumentVersion: 0,
      checklist: [false, false, false, false, false, false],
      exportMeta: { issuingOrg: "", issueDate: localDateValue(), template: "standard" },
      updatedAt: Date.now(),
    };
  }

  async function init() {
    cacheElements();
    restoreSettings();
    restoreAccessToken();
    restoreState();
    bindEvents();
    applyStateToUI();
    initializeCollectionDates();
    updateCounts();
    updateFacts();
    const ready = await bootstrap();
    if (ready) await loadArticleSources();
  }

  function cacheElements() {
    [
      "saveDot", "saveStatus", "historyButton", "serverDocumentsButton", "focusButton", "settingsButton", "quickExportButton",
      "inputPanel", "writingPanel", "reviewPanel", "writingForm", "loadExampleButton", "documentType",
      "length", "topic", "topicCount", "purpose", "audience", "referenceStyle", "requirements", "clearRequirements",
      "materials", "materialCount", "materialFile", "uploadMaterialButton", "materialFileName",
      "extractFactsButton", "factGroups", "factHint", "factLock", "documentBadge", "wordCount",
      "readingTime", "undoButton", "redoButton", "regenerateButton", "serverLibraryButton", "copyButton", "insertFieldButton", "generationHero", "generateButton",
      "documentWorkspace", "titleCandidates", "refreshTitlesButton", "documentTitle", "documentEditor",
      "paperType", "outlineRail", "outlineList", "collapseOutlineButton", "addSectionButton", "selectionToolbar",
      "qualityScore", "scoreRing", "qualityTitle", "qualitySummary", "reviewButton",
      "qualityMetrics", "factEvidence", "factCoverage", "factAuditSummary", "factEvidenceList", "issueCount", "issuesList", "checkProgress", "issuingOrg", "issueDate", "exportDocxButton",
      "batchExportButton", "printButton", "drawerBackdrop", "settingsDrawer", "historyDrawer", "providerName",
      "baseUrl", "modelName", "apiKey", "toggleApiKey", "apiSettings", "saveSettingsButton",
      "footerSettingsButton", "providerLabel", "connectionDot", "connectionLabel", "historyList",
      "createSnapshotButton", "batchModal", "batchCsv", "batchFile", "uploadBatchButton", "batchPreview",
      "batchEmpty", "batchRowCount", "batchFilename", "batchValidation", "generateBatchButton",
      "detectVariablesButton", "variableChips", "rewriteModal", "selectedPreview", "rewriteInstruction",
      "submitRewriteButton", "customRewriteButton", "loadingOverlay", "loadingTitle", "loadingMessage",
      "openArticleLibraryButton", "selectedReferences", "articleLibraryModal", "articleSearch", "articleSourceFilter",
      "searchArticlesButton", "articleList", "articleSource", "articleDate", "articleTitle", "articleUrl",
      "articleContent", "importArticleUrlButton", "saveArticleButton", "selectedArticleCount",
      "serverDocumentsModal", "serverDocumentList", "saveServerDocumentButton", "serverDocumentStatus",
      "testProviderButton", "providerTestStatus", "contentMethodology", "methodologyDescription",
      "customMethodologyDetails", "customMethodologyName", "customMethodologySteps", "titleWorkbench",
      "titleFormulaOptions", "customTitleFormulaDetails", "customTitleFormulaName", "customTitleFormulaTemplate",
      "customTitleFormulaRule", "titleCount", "titleSort", "titleCandidateSummary", "generateTitlesButton",
      "collectKeywords", "collectStartDate", "collectEndDate", "collectLimit", "collectArticlesButton",
      "collectionStatus", "collectionResults",
      "peopleCollectSourceLabel", "peopleSearchNotice",
      "accessModal", "accessForm", "accessToken", "accessError", "unlockAppButton",
      "accessSettings", "accessTokenSettingsButton", "serverProviderCard",
    ].forEach((id) => { if (document.getElementById(id)) els[id] = document.getElementById(id); });
  }

  function bindEvents() {
    const formInputs = $$('input:not([type="file"]), textarea, select', els.writingForm);
    formInputs.forEach((input) => {
      input.addEventListener("input", handleFormInput);
      input.addEventListener("change", handleFormInput);
    });
    els.documentTitle.addEventListener("input", handleDocumentInput);
    els.documentEditor.addEventListener("input", handleDocumentInput);
    els.documentEditor.addEventListener("paste", pasteAsPlainText);

    els.loadExampleButton.addEventListener("click", loadExample);
    els.clearRequirements.addEventListener("click", () => { els.requirements.value = ""; handleFormInput(); });
    els.extractFactsButton.addEventListener("click", updateFacts);
    els.uploadMaterialButton.addEventListener("click", () => els.materialFile.click());
    els.materialFile.addEventListener("change", importMaterialFile);
    els.generateButton.addEventListener("click", generateDocument);
    els.regenerateButton.addEventListener("click", generateDocument);
    els.serverDocumentsButton.addEventListener("click", openServerDocuments);
    els.serverLibraryButton.addEventListener("click", openServerDocuments);
    els.refreshTitlesButton.addEventListener("click", refreshTitleCandidates);
    els.generateTitlesButton.addEventListener("click", refreshTitleCandidates);
    els.titleSort.addEventListener("change", renderCandidates);
    els.contentMethodology.addEventListener("change", updateMethodologyView);
    [els.customMethodologyName, els.customMethodologySteps, els.customTitleFormulaName, els.customTitleFormulaTemplate, els.customTitleFormulaRule, els.titleCount]
      .forEach((control) => {
        control.addEventListener("input", () => { syncFormState(); scheduleSave(); });
        control.addEventListener("change", () => { syncFormState(); scheduleSave(); });
      });
    els.reviewButton.addEventListener("click", runReview);
    els.quickExportButton.addEventListener("click", exportDocx);
    els.exportDocxButton.addEventListener("click", exportDocx);
    els.batchExportButton.addEventListener("click", openBatchModal);
    els.printButton.addEventListener("click", () => window.print());
    els.copyButton.addEventListener("click", copyDocument);
    els.insertFieldButton.addEventListener("click", insertMergeField);
    els.undoButton.addEventListener("click", () => { els.documentEditor.focus(); document.execCommand("undo"); });
    els.redoButton.addEventListener("click", () => { els.documentEditor.focus(); document.execCommand("redo"); });
    $$('[data-format]').forEach((button) => button.addEventListener("click", () => applyFormat(button.dataset.format, button.dataset.value)));
    els.addSectionButton.addEventListener("click", addSection);
    els.collapseOutlineButton.addEventListener("click", () => {
      const collapsed = els.outlineRail.classList.toggle("is-collapsed");
      els.outlineRail.closest(".document-layout")?.classList.toggle("outline-collapsed", collapsed);
    });

    $$('.panel-tab').forEach((button) => button.addEventListener("click", () => switchSideTab(button)));
    $$('.mobile-tab').forEach((button) => button.addEventListener("click", () => switchMobilePanel(button)));
    $$('.template-option').forEach((option) => option.addEventListener("change", () => selectTemplate(true)));
    $$('.checklist input').forEach((checkbox, index) => checkbox.addEventListener("change", () => updateChecklist(index, checkbox.checked)));

    els.settingsButton.addEventListener("click", openSettings);
    els.footerSettingsButton.addEventListener("click", openSettings);
    els.historyButton.addEventListener("click", openHistory);
    $$('[data-close-drawer]').forEach((button) => button.addEventListener("click", closeDrawers));
    $$('[data-close-history]').forEach((button) => button.addEventListener("click", closeDrawers));
    els.drawerBackdrop.addEventListener("click", closeDrawers);
    els.saveSettingsButton.addEventListener("click", saveSettings);
    els.toggleApiKey.addEventListener("click", toggleApiKey);
    els.testProviderButton.addEventListener("click", testProviderConnection);
    els.providerName.addEventListener("change", resetProviderTestStatus);
    [els.baseUrl, els.modelName, els.apiKey].forEach((control) => control.addEventListener("input", resetProviderTestStatus));
    $$('input[name="engineMode"]').forEach((radio) => radio.addEventListener("change", updateSettingsMode));
    els.createSnapshotButton.addEventListener("click", () => createSnapshot("手动保存的版本", true));

    els.batchCsv.addEventListener("input", renderBatchPreview);
    els.uploadBatchButton.addEventListener("click", () => els.batchFile.click());
    els.batchFile.addEventListener("change", importBatchFile);
    els.detectVariablesButton.addEventListener("click", detectVariables);
    els.generateBatchButton.addEventListener("click", exportBatch);
    els.openArticleLibraryButton.addEventListener("click", openArticleLibrary);
    els.searchArticlesButton.addEventListener("click", loadArticles);
    els.articleSearch.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); loadArticles(); } });
    els.articleSourceFilter.addEventListener("change", loadArticles);
    els.saveArticleButton.addEventListener("click", saveArticleText);
    els.importArticleUrlButton.addEventListener("click", importArticleUrl);
    els.collectArticlesButton.addEventListener("click", collectArticles);
    els.saveServerDocumentButton.addEventListener("click", saveServerDocument);
    els.accessForm.addEventListener("submit", unlockApplication);
    els.accessModal.addEventListener("cancel", (event) => {
      if (accessTokenRequired) event.preventDefault();
    });
    els.accessTokenSettingsButton.addEventListener("click", () => {
      closeDrawers();
      showAccessGate("请输入新的访问令牌。");
    });

    document.addEventListener("selectionchange", trackEditorSelection);
    $$('[data-rewrite-mode]').forEach((button) => {
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", () => rewriteSelection(button.dataset.rewriteMode));
    });
    els.customRewriteButton.addEventListener("mousedown", (event) => event.preventDefault());
    els.customRewriteButton.addEventListener("click", openRewriteModal);
    els.submitRewriteButton.addEventListener("click", () => rewriteSelection("custom", els.rewriteInstruction.value));

    els.focusButton.addEventListener("click", () => { document.body.classList.toggle("focus-mode"); });
    document.addEventListener("keydown", handleKeyboard);
    window.addEventListener("beforeunload", persistState);
  }

  async function bootstrap() {
    try {
      const data = await apiRequest("/api/bootstrap");
      accessTokenRequired = Boolean(data.security?.access_token_required);
      serverProvider = {
        configured: Boolean(data.model?.server_provider_configured ?? data.server_provider_configured),
        providerName: String(data.model?.provider_name || ""),
        defaultModel: String(data.model?.default_model || ""),
      };
      configurePeopleSearch(Boolean(data.capabilities?.people_auto_discovery));
      updateDeploymentStatus();
      if (Array.isArray(data.document_types) && data.document_types.length) replaceOptions(els.documentType, data.document_types);
      if (Array.isArray(data.lengths) && data.lengths.length) replaceOptions(els.length, data.lengths.map((item) => ({ value: normalizeLength(typeof item === "string" ? item : item.value), label: typeof item === "string" ? item : item.label })));
      if (accessTokenRequired && !sessionAccessToken) {
        showAccessGate("请输入部署时设置的访问令牌。");
        setConnection(false);
        return false;
      }
      if (accessTokenRequired) await apiRequest("/api/article-sources");
      await loadMethodologyCatalog(false);
      setConnection(true);
      return true;
    } catch (error) {
      setConnection(false);
      console.info("Bootstrap unavailable; the saved interface remains usable.", error);
      return false;
    }
  }

  function configurePeopleSearch(enabled) {
    const input = $('input[name="collectSource"][value="people"]');
    if (!input) return;
    input.checked = false;
    input.disabled = !enabled;
    const disabledText = "人民网自动检索默认关闭；仍可在右侧手工导入 HTTPS 文章链接。";
    const enabledText = "人民网自动检索已由部署者显式开启；该检索接口使用 HTTP，关键词与日期范围会以明文传输，请按需手动勾选。";
    const text = enabled ? enabledText : disabledText;
    if (els.peopleCollectSourceLabel) els.peopleCollectSourceLabel.title = text;
    if (els.peopleSearchNotice) els.peopleSearchNotice.textContent = text;
  }

  async function loadMethodologyCatalog(resetToDefaults = false) {
    const requestSerial = ++catalogRequestSerial;
    const documentType = els.documentType.value || appState.form.document_type;
    try {
      const data = await apiRequest(`/api/methodologies?document_type=${encodeURIComponent(documentType)}`);
      if (requestSerial !== catalogRequestSerial) return;
      methodologyCatalog = {
        titleFormulas: Array.isArray(data.title_formulas) ? data.title_formulas : [],
        contentMethodologies: Array.isArray(data.content_methodologies) ? data.content_methodologies : [],
        defaults: Array.isArray(data.default_title_formula_ids) ? data.default_title_formula_ids : [],
        defaultMethodology: String(data.default_content_methodology_id || ""),
      };
      renderMethodologyCatalog(resetToDefaults);
    } catch (error) {
      if (requestSerial !== catalogRequestSerial) return;
      methodologyCatalog = fallbackMethodologyCatalog(documentType);
      renderMethodologyCatalog(resetToDefaults);
      console.info("Methodology catalog unavailable; using compact built-in choices.", error);
    }
  }

  function renderMethodologyCatalog(resetToDefaults) {
    const savedMethod = resetToDefaults ? "" : String(appState.form.content_methodology_id || els.contentMethodology.value || "");
    const defaultMethod = methodologyCatalog.defaultMethodology || methodologyCatalog.contentMethodologies[0]?.id || "universal-problem-solving";
    const methodOptions = methodologyCatalog.contentMethodologies.map((method) => makeOption(method.id, method.name));
    methodOptions.push(makeOption("custom", "＋ 自定义结构步骤"));
    els.contentMethodology.replaceChildren(...methodOptions);
    els.contentMethodology.value = [...els.contentMethodology.options].some((option) => option.value === savedMethod)
      ? savedMethod
      : defaultMethod;

    const savedFormulaIds = resetToDefaults
      ? methodologyCatalog.defaults
      : (Array.isArray(appState.form.title_formula_ids) && appState.form.title_formula_ids.length
          ? appState.form.title_formula_ids
          : methodologyCatalog.defaults);
    const selectedIds = new Set(savedFormulaIds);
    els.titleFormulaOptions.replaceChildren();
    methodologyCatalog.titleFormulas.forEach((formula) => {
      const label = document.createElement("label"); label.className = "title-formula-option";
      const input = document.createElement("input"); input.type = "checkbox"; input.value = String(formula.id || "");
      input.checked = selectedIds.has(input.value);
      const name = document.createElement("strong"); name.textContent = String(formula.name || formula.id || "标题公式");
      const template = document.createElement("code"); template.textContent = String(formula.template || "");
      const note = document.createElement("small"); note.textContent = String(formula.principle || formula.style || "");
      input.addEventListener("change", () => { syncFormState(); scheduleSave(); });
      label.append(input, name, template, note); els.titleFormulaOptions.append(label);
    });
    if (!methodologyCatalog.titleFormulas.length) {
      const empty = document.createElement("p"); empty.className = "formula-empty"; empty.textContent = "当前文种暂无预置公式，可使用自定义公式。"; els.titleFormulaOptions.append(empty);
    }
    updateMethodologyView();
    syncFormState();
    scheduleSave();
  }

  function updateMethodologyView() {
    const selectedId = els.contentMethodology.value;
    const method = methodologyCatalog.contentMethodologies.find((item) => item.id === selectedId);
    if (selectedId === "custom") {
      els.customMethodologyDetails.open = true;
      els.methodologyDescription.textContent = "将按你填写的步骤顺序组织一级标题和正文。";
    } else if (method) {
      const headings = Array.isArray(method.headings) ? method.headings.slice(0, 3).join("；") : "";
      els.methodologyDescription.textContent = [method.summary, method.logic, headings ? `结构示例：${headings}` : ""].filter(Boolean).join(" ");
    } else {
      els.methodologyDescription.textContent = "系统会根据文种匹配章节顺序、论证逻辑与事实使用规则。";
    }
    syncFormState(); scheduleSave();
  }

  function selectedTitleFormulaIds() {
    return $$('input[type="checkbox"]:checked', els.titleFormulaOptions).map((input) => input.value).filter(Boolean);
  }

  function customTitleFormulaPayload() {
    const template = els.customTitleFormulaTemplate.value.trim();
    if (!template) return null;
    return {
      name: els.customTitleFormulaName.value.trim() || "用户自定义公式",
      template,
      rule: els.customTitleFormulaRule.value.trim(),
      style: "自定义",
    };
  }

  function customMethodologyPayload() {
    if (els.contentMethodology.value !== "custom") return null;
    const steps = els.customMethodologySteps.value.split(/[\n；;]+/).map((item) => item.trim()).filter(Boolean);
    if (!steps.length) return null;
    const name = els.customMethodologyName.value.trim() || "用户自定义方法论";
    return {
      name,
      summary: `按“${steps.join("—")}”组织全文。`,
      logic: `依次展开${steps.join("、")}，各部分相互衔接。`,
      steps,
      fact_strategy: "具体名称、数字、日期和政策信息仅使用用户材料。",
    };
  }

  function fallbackMethodologyCatalog(documentType) {
    return {
      titleFormulas: [{ id: "generic-elements", name: "通用要素式", template: "关于{topic}的{document_type}", principle: "主题和文种要素完整。" }],
      contentMethodologies: [{ id: "universal-problem-solving", name: "通用问题求解法", summary: "从背景、问题、举措到保障层层推进。", logic: "先讲为什么，再讲做什么与怎么做。", headings: ["总体情况", "重点任务", "保障措施"], applicable_document_types: [documentType, "*"] }],
      defaults: ["generic-elements"],
      defaultMethodology: "universal-problem-solving",
    };
  }

  async function generateDocument() {
    syncFormState();
    if (!appState.form.topic.trim()) {
      els.topic.focus();
      els.topic.closest(".field").classList.add("has-error");
      toast("请先填写写作主题", "warning");
      return;
    }
    els.topic.closest(".field").classList.remove("has-error");
    if (els.contentMethodology.value === "custom" && !customMethodologyPayload()) {
      els.customMethodologyDetails.open = true;
      els.customMethodologySteps.focus();
      toast("请先填写自定义结构步骤", "warning");
      return;
    }
    showLoading("正在起草文稿", "梳理事实材料，搭建标题与段落结构……");
    try {
      if (documentPlainText()) createSnapshot("生成前的版本", false);
      const payload = { ...appState.form, selected_title: appState.document.title || undefined, style_references: appState.styleReferences, fact_lock: appState.form.factLock, live: settings.mode === "api", provider: providerPayload() };
      delete payload.factLock;
      const result = await apiRequest("/api/generate", { method: "POST", body: payload });
      applyGeneratedDocument(result);
      createSnapshot("生成初稿", false);
      toast("初稿已生成，可继续逐段修改", "success");
    } catch (error) {
      toast(readError(error, "生成失败，请稍后重试"), "error");
    } finally {
      hideLoading();
    }
  }

  async function refreshTitleCandidates() {
    syncFormState();
    if (!appState.form.topic.trim()) { els.topic.focus(); toast("请先填写写作主题", "warning"); return; }
    const formulaIds = selectedTitleFormulaIds();
    const customFormula = customTitleFormulaPayload();
    if (!formulaIds.length && !customFormula) {
      toast("请至少选择一种标题公式，或填写自定义公式", "warning");
      return;
    }
    if (els.customTitleFormulaDetails.open && !customFormula && els.customTitleFormulaTemplate.value.trim()) {
      els.customTitleFormulaTemplate.focus();
      toast("请检查自定义标题公式", "warning");
      return;
    }
    setButtonBusy(els.refreshTitlesButton, true, "构思中…");
    setButtonBusy(els.generateTitlesButton, true, "正在评分…");
    els.titleCandidateSummary.textContent = "正在生成并评估标题…";
    try {
      const payload = {
        document_type: appState.form.document_type,
        topic: appState.form.topic,
        purpose: appState.form.purpose,
        audience: appState.form.audience,
        materials: appState.form.materials,
        tone: appState.form.tone,
        reference_style: appState.form.reference_style,
        style_references: appState.styleReferences,
        count: Number(els.titleCount.value) || 5,
        formula_ids: formulaIds,
        custom_title_formula: customFormula,
        live: settings.mode === "api",
        provider: providerPayload(),
      };
      const result = await apiRequest("/api/titles/generate", { method: "POST", body: payload });
      appState.document.candidates = normalizeCandidates(result.candidates || result.title_candidates || result.titles || [], result.recommended_title || result.title);
      if (!appState.document.title || !documentPlainText()) {
        appState.document.title = String(result.recommended_title || appState.document.candidates[0]?.title || "");
        els.documentTitle.value = appState.document.title;
      }
      renderCandidates(); scheduleSave(); toast("标题已生成并按评分排序", "success");
    } catch (error) { toast(readError(error, "标题生成失败"), "error"); }
    finally {
      setButtonBusy(els.refreshTitlesButton, false);
      setButtonBusy(els.generateTitlesButton, false);
      updateTitleCandidateSummary();
    }
  }

  function applyGeneratedDocument(result) {
    const candidates = normalizeCandidates(result.title_candidates || result.titles || [], result.title);
    const outline = normalizeOutline(result.outline || []);
    const title = String(result.title || candidates[0]?.title || appState.form.topic);
    appState.document = { title, candidates, outline, html: "" };
    appState.review = null;
    appState.factAudit = null;
    els.documentTitle.value = title;
    renderContent(result.content, outline);
    appState.document.html = sanitizeHtml(els.documentEditor.innerHTML);
    renderCandidates();
    renderOutline();
    els.generationHero.classList.add("is-hidden");
    els.documentWorkspace.classList.remove("is-hidden");
    els.paperType.textContent = appState.form.document_type;
    resetReviewView();
    updateCounts();
    scheduleSave();
  }

  function renderContent(content, outline) {
    const fragment = document.createDocumentFragment();
    const source = String(content || "").trim();
    const lines = source ? source.split(/\n+/).map((line) => line.trim()).filter(Boolean) : [];
    if (!lines.length && outline.length) {
      outline.forEach((item) => lines.push(item.heading, item.content));
    }
    lines.forEach((line, index) => {
      const isHeading = /^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[.、])/.test(line);
      const node = document.createElement(isHeading ? "h2" : "p");
      node.textContent = line;
      if (isHeading) node.id = `section-${index}`;
      fragment.append(node);
    });
    els.documentEditor.replaceChildren(fragment);
  }

  function renderCandidates() {
    els.titleCandidates.replaceChildren();
    const candidates = sortedTitleCandidates(appState.document.candidates);
    els.titleCandidates.classList.toggle("is-empty", !candidates.length);
    if (!candidates.length) {
      const empty = document.createElement("div"); empty.className = "title-empty";
      const heading = document.createElement("b"); heading.textContent = "先定好题，再写正文";
      const copy = document.createElement("span"); copy.textContent = "填写左侧写作主题，然后在这里单独生成标题方案。";
      empty.append(heading, copy); els.titleCandidates.append(empty); updateTitleCandidateSummary(); return;
    }
    candidates.forEach((candidate, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `title-candidate${candidate.title === appState.document.title ? " is-selected" : ""}`;
      const number = document.createElement("span"); number.className = "candidate-number"; number.textContent = String(index + 1).padStart(2, "0");
      const copy = document.createElement("span"); copy.className = "candidate-copy";
      const top = document.createElement("span"); top.className = "candidate-top";
      const style = document.createElement("b"); style.textContent = candidate.formula_name || candidate.style || "标题方案";
      const score = document.createElement("span"); score.className = "title-score"; score.textContent = candidate.score == null ? "待评" : `${candidate.score} 分`;
      const title = document.createElement("strong"); title.textContent = candidate.title;
      const reason = document.createElement("small"); reason.textContent = candidate.reason || "结构完整，适合当前文种";
      const breakdown = document.createElement("span"); breakdown.className = "score-breakdown";
      titleScoreLabels(candidate).forEach(([label, value]) => {
        const chip = document.createElement("span"); chip.textContent = `${label} ${value}`; breakdown.append(chip);
      });
      const action = document.createElement("span"); action.className = "adopt-title-button";
      action.textContent = candidate.title === appState.document.title ? "已采用" : "一键采用";
      top.append(style, score); copy.append(top, title, reason, breakdown, action); button.append(number, copy);
      button.addEventListener("click", () => selectTitle(candidate.title));
      els.titleCandidates.append(button);
    });
    updateTitleCandidateSummary();
  }

  function sortedTitleCandidates(candidates) {
    const key = els.titleSort?.value || "score";
    const scoreKey = { compliance: "document_compliance", relevance: "topic_relevance", concision: "concision" }[key];
    return [...(Array.isArray(candidates) ? candidates : [])].sort((left, right) => {
      const leftScore = scoreKey ? Number(left.scores?.[scoreKey] ?? left.score_dimensions?.[scoreKey] ?? 0) : Number(left.score ?? 0);
      const rightScore = scoreKey ? Number(right.scores?.[scoreKey] ?? right.score_dimensions?.[scoreKey] ?? 0) : Number(right.score ?? 0);
      return rightScore - leftScore || Number(left.rank || 999) - Number(right.rank || 999);
    });
  }

  function titleScoreLabels(candidate) {
    const scores = candidate.scores || candidate.score_dimensions || {};
    const fields = [["规范", "document_compliance"], ["相关", "topic_relevance"], ["精炼", "concision"]];
    return fields.map(([label, key]) => [label, Number(scores[key])]).filter(([, value]) => Number.isFinite(value));
  }

  function updateTitleCandidateSummary() {
    if (!els.titleCandidateSummary) return;
    const candidates = Array.isArray(appState.document.candidates) ? appState.document.candidates : [];
    if (!candidates.length) { els.titleCandidateSummary.textContent = "尚未生成标题"; return; }
    const scores = candidates.map((item) => Number(item.score)).filter(Number.isFinite);
    const suffix = scores.length ? ` · 最高 ${Math.max(...scores)} 分` : "";
    els.titleCandidateSummary.textContent = `已生成 ${candidates.length} 个候选${suffix}`;
  }

  function renderOutline() {
    els.outlineList.replaceChildren();
    const headings = $$('h2, h3', els.documentEditor);
    const items = headings.length ? headings.map((heading) => ({ heading: heading.textContent || "未命名章节", content: "" })) : appState.document.outline;
    items.forEach((item, index) => {
      const li = document.createElement("li");
      const button = document.createElement("button"); button.type = "button";
      const number = document.createElement("span"); number.textContent = String(index + 1).padStart(2, "0");
      const text = document.createElement("b"); text.textContent = item.heading;
      button.append(number, text);
      button.addEventListener("click", () => (headings[index] || els.documentEditor).scrollIntoView({ behavior: "smooth", block: "center" }));
      li.append(button); els.outlineList.append(li);
    });
  }

  async function runReview() {
    const content = documentPlainText();
    if (!content) { toast("请先生成或输入正文", "warning"); return; }
    showLoading("正在检查文稿", "核对结构、表达、事实与待补信息……");
    try {
      const [reviewResult, auditResult] = await Promise.allSettled([
        apiRequest("/api/review", { method: "POST", body: { title: els.documentTitle.value.trim(), content, document_type: els.documentType.value, materials: els.materials.value, live: settings.mode === "api", provider: providerPayload() } }),
        apiRequest("/api/fact-audit", { method: "POST", body: { title: els.documentTitle.value.trim(), content, materials: els.materials.value } }),
      ]);
      if (reviewResult.status === "rejected" && auditResult.status === "rejected") throw reviewResult.reason;
      appState.review = reviewResult.status === "fulfilled" ? reviewResult.value : null;
      appState.factAudit = auditResult.status === "fulfilled" ? auditResult.value : null;
      if (appState.review) renderReview();
      else renderReviewUnavailable("语言与格式检查未完成，事实审校结果仍可查看。");
      if (appState.factAudit) renderFactAudit();
      else renderFactAuditUnavailable("事实审校未完成，语言与格式检查结果仍可查看。");
      scheduleSave();
      toast(reviewResult.status === "fulfilled" && auditResult.status === "fulfilled" ? "质量检查已完成" : "已完成部分检查，请查看提示", reviewResult.status === "fulfilled" && auditResult.status === "fulfilled" ? "success" : "warning");
    } catch (error) { toast(readError(error, "检查失败，请稍后重试"), "error"); }
    finally { hideLoading(); }
  }

  function renderReview() {
    const review = appState.review;
    if (!review) return;
    const auditMetrics = appState.factAudit?.metrics || {};
    const factPenalty = Math.min(35,
      (Number(auditMetrics.contradicted_sentence_count) || 0) * 12
      + (Number(auditMetrics.unverified_sentence_count) || 0) * 4
      + (Number(auditMetrics.partial_sentence_count) || 0) * 3);
    const score = Math.max(0, Math.min(100, (Number(review.score) || 0) - factPenalty));
    els.qualityScore.textContent = score;
    els.scoreRing.style.setProperty("--score", score);
    els.qualityTitle.textContent = score >= 90 ? "整体规范" : score >= 75 ? "建议优化" : "需要完善";
    els.qualitySummary.textContent = factPenalty
      ? `${review.summary || "语言与结构检查完成"} 另有事实陈述需要结合材料复核。`
      : review.summary || "检查完成，请结合建议逐项修改。";
    const combinedIssues = [
      ...(Array.isArray(review.issues) ? review.issues : []),
      ...(Array.isArray(appState.factAudit?.issues) ? appState.factAudit.issues : []),
    ];
    const issues = combinedIssues.filter((issue, index) => combinedIssues.findIndex((candidate) =>
      candidate.level === issue.level && candidate.category === issue.category
      && candidate.message === issue.message && candidate.suggestion === issue.suggestion) === index);
    const hasFactConflict = Number(auditMetrics.contradicted_sentence_count || 0) > 0;
    const unverifiedFacts = (Number(auditMetrics.unverified_sentence_count) || 0) + (Number(auditMetrics.partial_sentence_count) || 0);
    const factMetric = !els.materials.value.trim() ? "未核验" : !appState.factAudit ? "待重试" : hasFactConflict ? "疑似冲突" : unverifiedFacts ? `${unverifiedFacts}项待核` : "通过";
    const metricItems = [
      ["格式规范", score >= 80 ? "良好" : "待优化"],
      ["结构完整", Number(review.metrics?.heading_count || 0) > 0 ? "完整" : "待补充"],
      ["事实一致", factMetric],
      ["语言精炼", Number(review.metrics?.long_sentence_count || 0) === 0 ? "良好" : `${review.metrics.long_sentence_count}个长句`],
    ];
    els.qualityMetrics.replaceChildren(...metricItems.map(([label, value]) => {
      const row = document.createElement("div"); const span = document.createElement("span"); const b = document.createElement("b");
      span.textContent = label; b.textContent = value; row.append(span, b); return row;
    }));
    els.issueCount.textContent = `${issues.length} 条`;
    els.issuesList.classList.toggle("empty", !issues.length);
    els.issuesList.replaceChildren();
    if (!issues.length) {
      const p = document.createElement("p"); p.textContent = "暂未发现明显问题，请在正式使用前完成人工复核。"; els.issuesList.append(p);
    } else issues.forEach((issue) => {
      const article = document.createElement("article"); article.className = `issue-item ${issue.level || "suggestion"}`;
      const head = document.createElement("div"); const badge = document.createElement("span"); const category = document.createElement("b");
      badge.textContent = issue.level === "error" ? "需处理" : issue.level === "warning" ? "请留意" : "可优化"; category.textContent = issue.category || "表达"; head.append(badge, category);
      const message = document.createElement("p"); message.textContent = issue.message || "";
      const suggestion = document.createElement("small"); suggestion.textContent = issue.suggestion || "";
      article.append(head, message, suggestion); els.issuesList.append(article);
    });
  }

  function renderFactAudit() {
    const audit = appState.factAudit;
    els.factEvidenceList.replaceChildren();
    if (!audit) {
      els.factCoverage.textContent = "待检";
      els.factAuditSummary.textContent = "检查后将逐句标注材料依据、部分匹配和未核验陈述。";
      return;
    }
    const metrics = audit.metrics || {};
    const coverage = Math.max(0, Math.min(100, Number(metrics.evidence_coverage_percent) || 0));
    const factCount = Number(metrics.extracted_fact_count) || 0;
    const claimCount = Number(metrics.claim_sentence_count) || 0;
    const unsupported = (Number(metrics.partial_sentence_count) || 0) + (Number(metrics.unverified_sentence_count) || 0) + (Number(metrics.contradicted_sentence_count) || 0);
    els.factCoverage.textContent = factCount ? `${coverage}% 有依据` : "缺少材料";
    els.factAuditSummary.textContent = factCount
      ? `从材料提取 ${factCount} 项事实，检查 ${claimCount} 个陈述句，其中 ${unsupported} 个需要人工核对。`
      : "参考材料中尚无可比对事实，正文陈述暂标记为未核验。";
    const sentences = Array.isArray(audit.sentences) ? audit.sentences.filter((item) => item.has_claim).slice(0, 12) : [];
    if (!sentences.length) {
      const empty = document.createElement("p"); empty.className = "library-empty"; empty.textContent = "正文中暂未识别到需要溯源的陈述。"; els.factEvidenceList.append(empty); return;
    }
    const labels = { supported: "有材料依据", partial: "部分匹配", unverified: "未核验", contradicted: "疑似冲突" };
    const factsById = new Map((Array.isArray(audit.facts) ? audit.facts : []).map((fact) => [fact.fact_id, fact]));
    sentences.forEach((sentence) => {
      const status = String(sentence.status || "unverified");
      const item = document.createElement("article"); item.className = `evidence-item ${status}`;
      const badge = document.createElement("b"); badge.textContent = labels[status] || "待核对";
      const text = document.createElement("p"); text.textContent = sentence.text || "";
      const evidence = document.createElement("small");
      const links = Array.isArray(sentence.evidence) ? sentence.evidence : [];
      const evidenceCopy = [...new Set(links.map((link) => {
        const fact = factsById.get(link.fact_id);
        if (!fact) return link.fact_id;
        const excerpt = String(fact.excerpt || fact.value || "").replace(/\s+/g, " ").trim();
        return `${fact.source_label || "参考材料"}：${excerpt.slice(0, 72)}${excerpt.length > 72 ? "…" : ""}`;
      }))];
      evidence.textContent = evidenceCopy.length ? `依据：${evidenceCopy.join("；")}` : "依据：尚未匹配到材料事实";
      item.append(badge, text, evidence); els.factEvidenceList.append(item);
    });
  }

  function renderReviewUnavailable(message) {
    els.qualityScore.textContent = "—";
    els.scoreRing.style.setProperty("--score", 0);
    els.qualityTitle.textContent = "部分检查完成";
    els.qualitySummary.textContent = message;
    els.qualityMetrics.replaceChildren(...["格式规范", "结构完整", "事实一致", "语言精炼"].map((label) => {
      const row = document.createElement("div"); const span = document.createElement("span"); const value = document.createElement("b");
      span.textContent = label; value.textContent = label === "事实一致" && appState.factAudit ? `${appState.factAudit.metrics?.evidence_coverage_percent || 0}% 有依据` : "待重试";
      row.append(span, value); return row;
    }));
    els.issueCount.textContent = "0 条";
    els.issuesList.classList.add("empty");
    els.issuesList.replaceChildren();
    const note = document.createElement("p"); note.textContent = "当前仅展示已完成的检查模块，可稍后再次运行。"; els.issuesList.append(note);
  }

  function renderFactAuditUnavailable(message) {
    els.factCoverage.textContent = "待重试";
    els.factAuditSummary.textContent = message;
    els.factEvidenceList.replaceChildren();
  }

  async function exportDocx() {
    const content = documentPlainText();
    if (!content) { toast("请先生成或输入正文", "warning"); return; }
    setButtonBusy(els.exportDocxButton, true, "正在生成…");
    try {
      const filename = safeFilename(els.documentTitle.value || "公文") + ".docx";
      const response = await fetch("/api/export/docx", { method: "POST", headers: requestHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ title: els.documentTitle.value.trim() || "公文", content, template_style: selectedTemplate(), metadata: { document_type: els.documentType.value, issuing_org: els.issuingOrg.value.trim(), issue_date: els.issueDate.value }, filename }) });
      if (!response.ok) throw await responseError(response);
      downloadBlob(await response.blob(), filename);
      toast("Word 文件已生成", "success");
    } catch (error) { toast(readError(error, "导出失败，请稍后重试"), "error"); }
    finally { setButtonBusy(els.exportDocxButton, false); }
  }

  async function apiRequest(path, { method = "GET", body } = {}) {
    const options = { method, headers: requestHeaders({ Accept: "application/json" }) };
    if (body !== undefined) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
    const response = await fetch(path, options);
    if (!response.ok) {
      const error = await responseError(response);
      if (response.status === 401 && accessTokenRequired) {
        clearAccessToken();
        showAccessGate("访问令牌已失效，请重新输入。");
      }
      throw error;
    }
    return response.json();
  }

  function requestHeaders(base = {}) {
    const headers = { ...base };
    if (sessionAccessToken) headers.Authorization = `Bearer ${sessionAccessToken}`;
    return headers;
  }

  function openArticleLibrary() {
    renderSelectedReferences();
    els.articleLibraryModal.showModal();
    loadArticles();
  }

  async function loadArticles() {
    const params = new URLSearchParams();
    const query = els.articleSearch.value.trim();
    const sourceId = els.articleSourceFilter.value;
    if (query) params.set("q", query);
    if (sourceId) params.set("source_id", sourceId);
    params.set("limit", "100");
    els.articleList.replaceChildren();
    const loading = document.createElement("p"); loading.className = "library-empty"; loading.textContent = "正在读取文章来源库……"; els.articleList.append(loading);
    try {
      const result = await apiRequest(`/api/articles?${params.toString()}`);
      const items = Array.isArray(result) ? result : Array.isArray(result.items) ? result.items : [];
      renderArticleList(items);
    } catch (error) {
      els.articleList.replaceChildren();
      const message = document.createElement("p"); message.className = "library-empty"; message.textContent = readError(error, "文章来源库读取失败"); els.articleList.append(message);
    }
  }

  async function loadArticleSources() {
    try {
      const result = await apiRequest("/api/article-sources");
      const sources = Array.isArray(result?.items) ? result.items.filter((item) => item?.id && item?.name) : [];
      if (!sources.length) return;
      const filterValue = els.articleSourceFilter.value;
      const importValue = els.articleSource.value;
      els.articleSourceFilter.replaceChildren(makeOption("", "全部来源"), ...sources.map((item) => makeOption(item.id, item.name)), makeOption("manual", "用户导入"));
      els.articleSource.replaceChildren(...sources.map((item) => makeOption(item.id, item.name)), makeOption("manual", "用户导入"));
      els.articleSourceFilter.value = [...els.articleSourceFilter.options].some((option) => option.value === filterValue) ? filterValue : "";
      els.articleSource.value = [...els.articleSource.options].some((option) => option.value === importValue) ? importValue : "manual";
    } catch (_) { /* Built-in source choices remain available while offline. */ }
  }

  function makeOption(value, label) {
    const option = document.createElement("option"); option.value = String(value); option.textContent = String(label); return option;
  }

  function renderArticleList(items) {
    els.articleList.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p"); empty.className = "library-empty"; empty.textContent = "文章来源库为空，可在右侧添加。"; els.articleList.append(empty); return;
    }
    const selectedIds = new Set(appState.styleReferences.map((item) => item.id));
    items.forEach((raw) => {
      const reference = normalizeArticleReference(raw);
      const card = document.createElement("article"); card.className = `article-card${selectedIds.has(reference.id) ? " is-selected" : ""}`;
      const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.checked = selectedIds.has(reference.id); checkbox.setAttribute("aria-label", `选择${reference.title}`);
      const copy = document.createElement("div"); copy.className = "article-card-copy";
      const title = document.createElement("strong"); title.textContent = reference.title || "未命名文章";
      const meta = document.createElement("small"); meta.textContent = [reference.source_name, reference.published_at].filter(Boolean).join(" · ") || "用户导入";
      const summary = document.createElement("p"); summary.textContent = reference.excerpt || "暂无摘要";
      const features = document.createElement("em"); features.textContent = reference.style_features.length ? reference.style_features.join(" · ") : "等待提炼写法特征";
      copy.append(title, meta, summary, features);
      const remove = document.createElement("button"); remove.type = "button"; remove.className = "article-delete"; remove.textContent = "删除"; remove.setAttribute("aria-label", `删除${reference.title}`);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked && appState.styleReferences.length >= 8) { checkbox.checked = false; toast("每次最多选择 8 篇参考文章", "warning"); return; }
        if (checkbox.checked) appState.styleReferences = [...appState.styleReferences.filter((item) => item.id !== reference.id), reference];
        else appState.styleReferences = appState.styleReferences.filter((item) => item.id !== reference.id);
        card.classList.toggle("is-selected", checkbox.checked); renderSelectedReferences(); scheduleSave();
      });
      remove.addEventListener("click", () => deleteArticle(reference.id, reference.title));
      card.append(checkbox, copy, remove); els.articleList.append(card);
    });
  }

  function normalizeArticleReference(raw) {
    return {
      id: String(raw?.id || ""),
      title: String(raw?.title || ""),
      source_name: String(raw?.source_name || raw?.source || "用户导入"),
      url: String(raw?.url || ""),
      published_at: String(raw?.published_date || raw?.published_at || ""),
      excerpt: String(raw?.summary || raw?.excerpt || "").slice(0, 1000),
      style_features: Array.isArray(raw?.style_features) ? raw.style_features.map(String).slice(0, 12) : [],
    };
  }

  function renderSelectedReferences() {
    const references = Array.isArray(appState.styleReferences) ? appState.styleReferences : [];
    els.selectedReferences.replaceChildren();
    els.selectedReferences.classList.toggle("empty", !references.length);
    if (!references.length) els.selectedReferences.textContent = "尚未选择参考文章";
    references.forEach((reference) => {
      const chip = document.createElement("span"); chip.className = "reference-chip";
      const label = document.createElement("span"); label.textContent = `${reference.source_name}｜${reference.title}`;
      const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "×"; remove.setAttribute("aria-label", `移除${reference.title}`);
      remove.addEventListener("click", () => { appState.styleReferences = appState.styleReferences.filter((item) => item.id !== reference.id); renderSelectedReferences(); scheduleSave(); });
      chip.append(label, remove); els.selectedReferences.append(chip);
    });
    els.selectedArticleCount.textContent = `已选择 ${references.length} 篇`;
  }

  async function saveArticleText() {
    const title = els.articleTitle.value.trim(); const content = els.articleContent.value.trim();
    if (!title || !content) { toast("请填写文章标题和正文", "warning"); return; }
    setButtonBusy(els.saveArticleButton, true, "正在保存…");
    try {
      const sourceId = els.articleSource.value || "manual";
      const result = await apiRequest("/api/articles/import-text", { method: "POST", body: { title, content, source_id: sourceId, source_name: sourceLabel(sourceId), url: els.articleUrl.value.trim() || undefined, published_date: els.articleDate.value || undefined } });
      addSelectedReference(result); clearArticleForm(); await loadArticles(); toast("文章已保存并选为写法参考", "success");
    } catch (error) { toast(readError(error, "文章保存失败"), "error"); }
    finally { setButtonBusy(els.saveArticleButton, false); }
  }

  async function importArticleUrl() {
    const url = els.articleUrl.value.trim();
    if (!url) { els.articleUrl.focus(); toast("请填写官方网站文章链接", "warning"); return; }
    setButtonBusy(els.importArticleUrlButton, true, "正在读取…");
    try {
      const sourceId = els.articleSource.value === "manual" ? undefined : els.articleSource.value;
      const result = await apiRequest("/api/articles/import-url", { method: "POST", body: { url, source_id: sourceId } });
      addSelectedReference(result); clearArticleForm(); await loadArticles(); toast("文章已读取并保存到本地库", "success");
    } catch (error) { toast(readError(error, "文章链接读取失败"), "error"); }
    finally { setButtonBusy(els.importArticleUrlButton, false); }
  }

  function addSelectedReference(raw) {
    const reference = normalizeArticleReference(raw);
    if (!reference.id) return;
    appState.styleReferences = [...appState.styleReferences.filter((item) => item.id !== reference.id), reference].slice(-8);
    renderSelectedReferences(); scheduleSave();
  }

  async function deleteArticle(articleId, articleTitle = "这篇文章") {
    if (!window.confirm(`确定从本地文章来源库删除“${articleTitle}”吗？`)) return;
    try {
      await apiRequest(`/api/articles/${encodeURIComponent(articleId)}`, { method: "DELETE" });
      appState.styleReferences = appState.styleReferences.filter((item) => item.id !== articleId);
      renderSelectedReferences(); await loadArticles(); toast("文章已从本地库删除", "success");
    } catch (error) { toast(readError(error, "文章删除失败"), "error"); }
  }

  function clearArticleForm() {
    els.articleTitle.value = ""; els.articleUrl.value = ""; els.articleDate.value = ""; els.articleContent.value = "";
  }

  function sourceLabel(sourceId) {
    return { people: "人民日报 / 人民网", gmw: "光明日报 / 光明网", qiushi: "求是 / 求是网", manual: "用户导入" }[sourceId] || "用户导入";
  }

  function initializeCollectionDates() {
    if (!els.collectEndDate || !els.collectStartDate) return;
    const today = localDateValue();
    const start = new Date(); start.setDate(start.getDate() - 90);
    const localStart = new Date(start.getTime() - start.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    els.collectEndDate.max = today; els.collectStartDate.max = today;
    if (!els.collectEndDate.value) els.collectEndDate.value = today;
    if (!els.collectStartDate.value) els.collectStartDate.value = localStart;
  }

  async function collectArticles() {
    const keywords = els.collectKeywords.value.split(/[,，;；\n]+/).map((item) => item.trim()).filter(Boolean);
    const sourceIds = $$('input[name="collectSource"]:checked').map((input) => input.value);
    if (!keywords.length) { els.collectKeywords.focus(); toast("请至少填写一个采集关键词", "warning"); return; }
    if (!sourceIds.length) { toast("请至少选择一个文章来源", "warning"); return; }
    if (els.collectStartDate.value && els.collectEndDate.value && els.collectStartDate.value > els.collectEndDate.value) {
      els.collectStartDate.focus(); toast("开始日期应早于结束日期", "warning"); return;
    }
    setButtonBusy(els.collectArticlesButton, true, "正在采集…");
    els.collectionStatus.textContent = `正在检索 ${sourceIds.length} 个来源…`;
    els.collectionResults.replaceChildren();
    const loading = document.createElement("p"); loading.className = "collection-empty is-loading"; loading.textContent = "正在发现文章并写入本地资料库…"; els.collectionResults.append(loading);
    try {
      const result = await apiRequest("/api/articles/auto-collect", {
        method: "POST",
        body: {
          keywords,
          source_ids: sourceIds,
          start_date: els.collectStartDate.value || null,
          end_date: els.collectEndDate.value || null,
          limit: Math.max(1, Math.min(100, Number(els.collectLimit.value) || 20)),
        },
      });
      renderCollectionResults(result);
      await loadArticles();
      const imported = Number(result.imported_count) || 0;
      toast(imported ? `已将 ${imported} 篇文章加入本地库` : "采集已完成，请查看结果", imported ? "success" : "warning");
    } catch (error) {
      els.collectionResults.replaceChildren();
      const message = document.createElement("p"); message.className = "collection-empty error"; message.textContent = readError(error, "范围采集失败"); els.collectionResults.append(message);
      els.collectionStatus.textContent = "采集未完成";
      toast(readError(error, "范围采集失败"), "error");
    } finally {
      setButtonBusy(els.collectArticlesButton, false);
    }
  }

  function renderCollectionResults(result) {
    const items = Array.isArray(result?.items) ? result.items : [];
    const errors = Array.isArray(result?.source_errors) ? result.source_errors : [];
    const imported = Number(result?.imported_count) || 0;
    const duplicate = Number(result?.duplicate_count) || 0;
    const failed = Number(result?.failed_count) || 0;
    els.collectionStatus.textContent = `发现 ${Number(result?.discovered_count) || 0} 篇 · 新增 ${imported} 篇 · 重复 ${duplicate} 篇${failed ? ` · 异常 ${failed} 项` : ""}`;
    els.collectionResults.replaceChildren();
    [...items, ...errors].forEach((item) => {
      const article = document.createElement("article"); article.className = `collector-result ${item.status || "failed"}`;
      const copy = document.createElement("div");
      const title = document.createElement("strong"); title.textContent = String(item.title || sourceLabel(item.source_id) || "采集结果");
      const meta = document.createElement("small");
      const statusLabel = { imported: "已入库", duplicate: "已存在", skipped: "已跳过", failed: "未完成" }[item.status] || "已处理";
      meta.textContent = [sourceLabel(item.source_id), item.published_date, item.message].filter(Boolean).join(" · ");
      copy.append(title, meta);
      const badge = document.createElement("span"); badge.className = "result-status"; badge.textContent = statusLabel;
      article.append(copy, badge); els.collectionResults.append(article);
    });
    if (!items.length && !errors.length) {
      const empty = document.createElement("p"); empty.className = "collection-empty"; empty.textContent = "当前范围内没有新文章，可调整关键词或日期后重试。"; els.collectionResults.append(empty);
    }
  }

  function openServerDocuments() {
    els.serverDocumentsModal.showModal();
    loadServerDocuments();
  }

  async function loadServerDocuments() {
    els.serverDocumentList.replaceChildren();
    const loading = document.createElement("p"); loading.className = "library-empty"; loading.textContent = "正在读取文稿……"; els.serverDocumentList.append(loading);
    try {
      const result = await apiRequest("/api/documents?limit=100");
      const items = Array.isArray(result) ? result : Array.isArray(result.items) ? result.items : [];
      renderServerDocuments(items);
    } catch (error) {
      els.serverDocumentList.replaceChildren();
      const message = document.createElement("p"); message.className = "library-empty"; message.textContent = readError(error, "服务端文稿读取失败"); els.serverDocumentList.append(message);
    }
  }

  function renderServerDocuments(items) {
    els.serverDocumentList.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p"); empty.className = "library-empty"; empty.textContent = "服务端尚无文稿，可保存当前正文。"; els.serverDocumentList.append(empty); return;
    }
    items.forEach((record) => {
      const item = document.createElement("article"); item.className = `server-document-item${record.id === appState.serverDocumentId ? " is-current" : ""}`;
      const copy = document.createElement("div"); const title = document.createElement("strong"); const meta = document.createElement("small");
      title.textContent = record.title || "未命名文稿";
      meta.textContent = `${record.document_type || "工作稿"} · 第 ${record.current_version || 1} 版 · ${formatDateTime(record.updated_at)}`;
      copy.append(title, meta);
      const actions = document.createElement("div"); actions.className = "server-document-actions";
      const open = document.createElement("button"); open.type = "button"; open.textContent = "打开"; open.addEventListener("click", () => openServerDocument(record.id));
      const versions = document.createElement("button"); versions.type = "button"; versions.textContent = "版本";
      const remove = document.createElement("button"); remove.type = "button"; remove.className = "danger"; remove.textContent = "删除"; remove.addEventListener("click", () => deleteServerDocument(record.id));
      const versionList = document.createElement("div"); versionList.className = "server-version-list"; versionList.hidden = true;
      versions.addEventListener("click", () => toggleServerVersions(record, versionList, versions));
      actions.append(open, versions, remove); item.append(copy, actions, versionList); els.serverDocumentList.append(item);
    });
  }

  async function saveServerDocument() {
    const content = documentPlainText(); const title = els.documentTitle.value.trim();
    if (!title || !content) { toast("请先生成或输入完整文稿", "warning"); return; }
    persistState();
    setButtonBusy(els.saveServerDocumentButton, true, "正在保存…");
    try {
      const result = await apiRequest("/api/documents", { method: "POST", body: {
        id: appState.serverDocumentId || undefined,
        expected_version: appState.serverDocumentId ? appState.serverDocumentVersion : 0,
        title,
        content,
        document_type: els.documentType.value,
        version_note: appState.serverDocumentId ? "从写作工作台更新" : "首次保存",
        metadata: {
          form: appState.form,
          style_references: appState.styleReferences,
          export_meta: appState.exportMeta,
          document_html: sanitizeHtml(els.documentEditor.innerHTML),
        },
      } });
      appState.serverDocumentId = result.id;
      appState.serverDocumentVersion = Number(result.current_version) || 1;
      els.serverDocumentStatus.textContent = `已保存 · 第 ${appState.serverDocumentVersion} 版`;
      persistState(); await loadServerDocuments(); toast("文稿和版本已保存到本机服务端", "success");
    } catch (error) {
      if (error?.payload?.error?.code === "version_conflict") {
        els.serverDocumentStatus.textContent = "检测到其他页面的新版本，请先重新打开后再保存";
        await loadServerDocuments();
      }
      toast(readError(error, "服务端保存失败"), "error");
    }
    finally { setButtonBusy(els.saveServerDocumentButton, false); }
  }

  async function openServerDocument(documentId) {
    try {
      const record = await apiRequest(`/api/documents/${encodeURIComponent(documentId)}`);
      const metadata = record.metadata && typeof record.metadata === "object" ? record.metadata : {};
      appState.form = { ...freshState().form, ...(metadata.form || {}), document_type: record.document_type || metadata.form?.document_type || "工作总结" };
      appState.styleReferences = Array.isArray(metadata.style_references) ? metadata.style_references.map(normalizeArticleReference) : [];
      appState.exportMeta = { ...freshState().exportMeta, ...(metadata.export_meta || {}) };
      appState.document = { title: record.title || "", html: metadata.document_html ? sanitizeHtml(String(metadata.document_html)) : htmlFromPlainText(record.content || ""), candidates: [], outline: [] };
      appState.review = null; appState.factAudit = null;
      appState.serverDocumentId = record.id;
      appState.serverDocumentVersion = Number(record.current_version) || 1;
      els.serverDocumentStatus.textContent = `当前为第 ${appState.serverDocumentVersion} 版`;
      applyStateToUI(); persistState(); els.serverDocumentsModal.close(); toast(`已打开第 ${appState.serverDocumentVersion} 版文稿`, "success");
    } catch (error) { toast(readError(error, "文稿打开失败"), "error"); }
  }

  async function deleteServerDocument(documentId) {
    if (!window.confirm("确定删除这份服务端文稿及其全部版本吗？")) return;
    try {
      await apiRequest(`/api/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
      if (appState.serverDocumentId === documentId) { appState.serverDocumentId = ""; appState.serverDocumentVersion = 0; els.serverDocumentStatus.textContent = "当前文稿已从服务端删除"; persistState(); }
      await loadServerDocuments(); toast("服务端文稿已删除", "success");
    } catch (error) { toast(readError(error, "文稿删除失败"), "error"); }
  }

  async function toggleServerVersions(record, container, button) {
    if (!container.hidden) { container.hidden = true; button.textContent = "版本"; return; }
    container.hidden = false; container.replaceChildren(); button.textContent = "收起";
    const loading = document.createElement("p"); loading.className = "library-empty"; loading.textContent = "正在读取版本……"; container.append(loading);
    try {
      const result = await apiRequest(`/api/documents/${encodeURIComponent(record.id)}/versions?limit=100`);
      const versions = Array.isArray(result?.items) ? result.items : [];
      container.replaceChildren();
      if (!versions.length) { loading.textContent = "暂无历史版本"; container.append(loading); return; }
      versions.forEach((version) => {
        const row = document.createElement("div"); row.className = "server-version-item";
        const copy = document.createElement("span"); const title = document.createElement("b"); const time = document.createElement("small");
        title.textContent = `第 ${version.version || 1} 版${Number(version.version) === Number(record.current_version) ? " · 当前" : ""}`;
        time.textContent = [version.note, formatDateTime(version.created_at)].filter(Boolean).join(" · "); copy.append(title, time);
        const restore = document.createElement("button"); restore.type = "button"; restore.textContent = Number(version.version) === Number(record.current_version) ? "打开" : "恢复为新版本";
        restore.addEventListener("click", () => openServerVersion(record, version));
        row.append(copy, restore); container.append(row);
      });
    } catch (error) {
      container.replaceChildren(); const message = document.createElement("p"); message.className = "library-empty"; message.textContent = readError(error, "版本读取失败"); container.append(message);
    }
  }

  function openServerVersion(record, version) {
    const metadata = version.metadata && typeof version.metadata === "object" ? version.metadata : {};
    appState.form = { ...freshState().form, ...(metadata.form || {}), document_type: version.document_type || metadata.form?.document_type || "工作总结" };
    appState.styleReferences = Array.isArray(metadata.style_references) ? metadata.style_references.map(normalizeArticleReference).slice(0, 8) : [];
    appState.exportMeta = { ...freshState().exportMeta, ...(metadata.export_meta || {}) };
    appState.document = { title: version.title || "", html: metadata.document_html ? sanitizeHtml(String(metadata.document_html)) : htmlFromPlainText(version.content || ""), candidates: [], outline: [] };
    appState.review = null; appState.factAudit = null; appState.serverDocumentId = record.id; appState.serverDocumentVersion = Number(record.current_version) || Number(version.version) || 1;
    applyStateToUI(); persistState(); els.serverDocumentsModal.close();
    toast(Number(version.version) === Number(record.current_version) ? "已打开当前版本" : `已载入第 ${version.version} 版，保存后将生成新版本`, "success");
  }

  function htmlFromPlainText(value) {
    const container = document.createElement("div");
    String(value || "").split(/\n+/).map((line) => line.trim()).filter(Boolean).forEach((line) => {
      const heading = /^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[.、])/.test(line);
      const node = document.createElement(heading ? "h2" : "p"); node.textContent = line; container.append(node);
    });
    return container.innerHTML;
  }

  async function responseError(response) {
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* binary or empty error response */ }
    const error = new Error(payload?.error?.message || payload?.detail || `请求失败（${response.status}）`);
    error.payload = payload;
    return error;
  }

  function providerPayload() {
    if (settings.mode !== "api") return undefined;
    if (serverProvider.configured && !sessionApiKey && !settings.baseUrl && !settings.modelName) return undefined;
    const aliases = { deepseek: "openai", qwen: "openai", custom: "openai" };
    return { name: aliases[settings.providerName] || settings.providerName || "openai", model: settings.modelName || undefined, api_key: sessionApiKey || undefined, base_url: settings.baseUrl || undefined };
  }

  function readError(error, fallback) { return error instanceof Error && error.message ? error.message : fallback; }

  function handleFormInput() {
    const previousDocumentType = appState.form.document_type;
    syncFormState();
    if (appState.review || appState.factAudit) {
      appState.review = null; appState.factAudit = null; resetReviewView();
    }
    els.documentBadge.textContent = appState.form.document_type;
    els.paperType.textContent = appState.form.document_type;
    updateCounts();
    clearTimeout(factTimer);
    factTimer = window.setTimeout(updateFacts, 350);
    if (previousDocumentType !== appState.form.document_type) loadMethodologyCatalog(true);
    scheduleSave();
  }

  function handleDocumentInput() {
    appState.document.title = els.documentTitle.value;
    appState.document.html = sanitizeHtml(els.documentEditor.innerHTML);
    appState.review = null;
    appState.factAudit = null;
    resetReviewView();
    updateCounts();
    renderOutline();
    scheduleSave();
  }

  function syncFormState() {
    appState.form = {
      document_type: els.documentType.value,
      topic: els.topic.value,
      purpose: els.purpose.value,
      audience: els.audience.value,
      tone: $('input[name="tone"]:checked')?.value || "严谨规范",
      reference_style: els.referenceStyle.value,
      length: els.length.value,
      requirements: els.requirements.value,
      materials: els.materials.value,
      factLock: els.factLock.checked,
      content_methodology_id: els.contentMethodology?.value || "",
      custom_methodology: customMethodologyPayload(),
      title_formula_ids: selectedTitleFormulaIds(),
      title_count: Math.max(1, Math.min(20, Number(els.titleCount?.value) || 5)),
      custom_title_formula: customTitleFormulaPayload(),
    };
    appState.exportMeta = { issuingOrg: els.issuingOrg.value, issueDate: els.issueDate.value, template: selectedTemplate() };
  }

  function updateCounts() {
    els.topicCount.textContent = String(els.topic.value.length);
    els.materialCount.textContent = String(countChinese(els.materials.value));
    const count = countChinese(documentPlainText());
    els.wordCount.textContent = `${count} 字`;
    els.readingTime.textContent = String(Math.max(1, Math.ceil(count / 420)));
  }

  function updateFacts() {
    const material = els.materials.value.trim();
    const groups = extractFacts(material);
    els.factGroups.replaceChildren();
    if (!material) {
      els.factHint.textContent = "粘贴材料后，将自动识别时间、数字、机构和任务。";
      return;
    }
    const total = Object.values(groups).reduce((sum, values) => sum + values.length, 0);
    els.factHint.textContent = total ? `已从材料中识别 ${total} 项关键信息。` : "已读取材料，暂未识别到明确事实，可继续补充。";
    const labels = { dates: ["时间", "时"], numbers: ["数字", "数"], organizations: ["机构", "机"], tasks: ["任务", "任"] };
    Object.entries(groups).forEach(([key, values]) => {
      if (!values.length) return;
      const section = document.createElement("section"); section.className = "fact-group";
      const head = document.createElement("h4"); const icon = document.createElement("i"); const text = document.createElement("span");
      icon.textContent = labels[key][1]; icon.setAttribute("aria-hidden", "true"); text.textContent = labels[key][0]; head.append(icon, text);
      const list = document.createElement("div");
      values.slice(0, key === "tasks" ? 4 : 6).forEach((value) => { const item = document.createElement("span"); item.textContent = value; item.title = value; list.append(item); });
      section.append(head, list); els.factGroups.append(section);
    });
  }

  function extractFacts(text) {
    const unique = (values) => [...new Set(values.map((value) => value.trim()).filter(Boolean))];
    const dates = unique(text.match(/(?:20\d{2}年)?\d{1,2}月(?:\d{1,2}日|底|前|初|中旬|下旬)?|20\d{2}年度?/g) || []);
    const numbers = unique(text.match(/\d+(?:\.\d+)?(?:%|％|亿元|万元|万|项|个|家|名|次|套|份|天|月|年)/g) || []).filter((value) => !dates.some((date) => date.includes(value))).slice(0, 8);
    const organizations = unique((text.match(/[\u4e00-\u9fa5]{2,12}(?:办公室|信息中心|委员会|处室|单位|部门|中心|公司|学院|局|厅)/g) || [])).slice(0, 7);
    const tasks = unique(text.split(/[。；！？\n]+/).filter((line) => /(?:负责|完成|推进|形成|明确|落实|建立|开展|上线|确保)/.test(line) && line.length >= 6)).slice(0, 4);
    return { dates, numbers, organizations, tasks };
  }

  function loadExample() {
    els.documentType.value = EXAMPLE.document_type;
    els.topic.value = EXAMPLE.topic;
    els.purpose.value = EXAMPLE.purpose;
    els.audience.value = EXAMPLE.audience;
    els.length.value = EXAMPLE.length;
    els.referenceStyle.value = EXAMPLE.reference_style;
    els.requirements.value = EXAMPLE.requirements;
    els.materials.value = EXAMPLE.materials;
    const tone = $(`input[name="tone"][value="${EXAMPLE.tone}"]`); if (tone) tone.checked = true;
    handleFormInput();
    toast("示例材料已填入，点击“生成公文初稿”查看效果", "success");
  }

  async function importMaterialFile() {
    const file = els.materialFile.files?.[0]; if (!file) return;
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error("文件请控制在 2MB 以内");
      const text = await file.text();
      els.materials.value = [els.materials.value.trim(), text.trim()].filter(Boolean).join("\n\n");
      els.materialFileName.textContent = file.name;
      handleFormInput();
      toast("材料已导入", "success");
    } catch (error) { toast(readError(error, "文件读取失败"), "error"); }
    finally { els.materialFile.value = ""; }
  }

  function selectTitle(title) {
    appState.document.title = title;
    els.documentTitle.value = title;
    appState.review = null; appState.factAudit = null; resetReviewView();
    renderCandidates();
    toast("已采用该标题，生成正文时将优先使用", "success");
    scheduleSave();
  }

  function normalizeCandidates(candidates, selectedTitle) {
    const normalized = candidates.map((item, index) => typeof item === "string"
      ? { title: item, style: ["稳健规范", "凝练概括", "部署有力", "并列对仗"][index] || "备选", reason: "", rank: index + 1 }
      : {
          title: String(item.title || item.text || ""),
          style: String(item.style || "标题方案"),
          reason: String(item.reason || ""),
          formula_id: String(item.formula_id || ""),
          formula_name: String(item.formula_name || ""),
          score: Number.isFinite(Number(item.score)) ? Number(item.score) : null,
          scores: item.scores && typeof item.scores === "object" ? item.scores : (item.score_dimensions || {}),
          score_dimensions: item.score_dimensions && typeof item.score_dimensions === "object" ? item.score_dimensions : (item.scores || {}),
          rank: Math.max(1, Number(item.rank) || index + 1),
        }).filter((item) => item.title);
    if (!normalized.length && selectedTitle) normalized.push({ title: String(selectedTitle), style: "稳健规范", reason: "要素完整，适合当前文种" });
    return normalized;
  }

  function normalizeOutline(outline) {
    return outline.map((item) => typeof item === "string" ? { heading: item, content: "" } : { heading: String(item.heading || item.title || ""), content: String(item.content || "") }).filter((item) => item.heading);
  }

  function addSection() {
    if (els.documentWorkspace.classList.contains("is-hidden")) return;
    const heading = document.createElement("h2"); heading.textContent = `${chineseNumber($$('h2', els.documentEditor).length + 1)}、新增章节`;
    const paragraph = document.createElement("p"); paragraph.textContent = "请在此补充具体内容。";
    els.documentEditor.append(heading, paragraph); handleDocumentInput(); heading.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function applyFormat(command, value) {
    els.documentEditor.focus();
    document.execCommand(command, false, value || null);
    handleDocumentInput();
  }

  function pasteAsPlainText(event) {
    event.preventDefault();
    const text = event.clipboardData?.getData("text/plain") || "";
    document.execCommand("insertText", false, text);
  }

  async function copyDocument() {
    const text = [els.documentTitle.value.trim(), documentPlainText()].filter(Boolean).join("\n\n");
    if (!text) { toast("暂无可复制内容", "warning"); return; }
    try { await navigator.clipboard.writeText(text); toast("全文已复制", "success"); }
    catch (_) {
      const area = document.createElement("textarea"); area.value = text; document.body.append(area); area.select(); document.execCommand("copy"); area.remove(); toast("全文已复制", "success");
    }
  }

  function insertMergeField() {
    const rawName = window.prompt("输入字段名，例如：单位、日期、责任人", "单位");
    if (rawName === null) return;
    const name = rawName.trim().replace(/[{}\r\n]/g, "").slice(0, 30);
    if (!name) { toast("请输入有效字段名", "warning"); return; }
    els.documentEditor.focus();
    const field = `{{${name}}}`;
    const selection = window.getSelection();
    const insideEditor = Boolean(selection && selection.rangeCount && selection.anchorNode && els.documentEditor.contains(selection.anchorNode));
    if (insideEditor) document.execCommand("insertText", false, field);
    else {
      const paragraph = document.createElement("p"); paragraph.textContent = field; els.documentEditor.append(paragraph);
    }
    handleDocumentInput();
    toast(`已插入 Word 域：${name}`, "success");
  }

  function trackEditorSelection() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) { hideSelectionToolbar(); return; }
    const range = selection.getRangeAt(0);
    const ancestor = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement;
    if (!ancestor || !els.documentEditor.contains(ancestor) || selection.toString().trim().length < 2) { hideSelectionToolbar(); return; }
    savedSelection = range.cloneRange();
    const rect = range.getBoundingClientRect();
    els.selectionToolbar.style.left = `${Math.max(12, Math.min(window.innerWidth - 390, rect.left + rect.width / 2 - 180))}px`;
    els.selectionToolbar.style.top = `${Math.max(58, rect.top - 48)}px`;
    els.selectionToolbar.classList.add("is-visible");
  }

  function hideSelectionToolbar() { els.selectionToolbar.classList.remove("is-visible"); }

  function openRewriteModal() {
    if (!savedSelection) return;
    els.selectedPreview.textContent = savedSelection.toString();
    els.rewriteInstruction.value = "";
    hideSelectionToolbar();
    els.rewriteModal.showModal();
    setTimeout(() => els.rewriteInstruction.focus(), 50);
  }

  async function rewriteSelection(mode, instruction = "") {
    if (!savedSelection || !savedSelection.toString().trim()) { toast("请先选中需要改写的文字", "warning"); return; }
    const range = savedSelection.cloneRange();
    const text = range.toString();
    if (mode === "custom" && !instruction.trim()) { els.rewriteInstruction.focus(); return; }
    if (els.rewriteModal.open) els.rewriteModal.close();
    hideSelectionToolbar();
    showLoading("正在改写选中内容", "保持事实不变，调整表达和句式……");
    try {
      const result = await apiRequest("/api/rewrite", { method: "POST", body: { text, instruction: instruction || rewriteInstruction(mode), mode, tone: appState.form.tone, live: settings.mode === "api", provider: providerPayload() } });
      if (!els.documentEditor.contains(range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement)) throw new Error("原文已发生变化，请重新选择");
      range.deleteContents();
      range.insertNode(document.createTextNode(String(result.text || text)));
      els.documentEditor.normalize();
      handleDocumentInput();
      createSnapshot("局部改写", false);
      toast(Array.isArray(result.changes) && result.changes.length ? result.changes.join("；") : "改写已完成", "success");
    } catch (error) { toast(readError(error, "改写失败，请稍后重试"), "error"); }
    finally { hideLoading(); savedSelection = null; }
  }

  function rewriteInstruction(mode) {
    return { polish: "提升表达的规范性、准确性和流畅度", concise: "删除重复和铺垫，保留全部事实并精简表达", expand: "围绕原意适度扩写，补充落实抓手但不新增事实数据", formal: "调整为严谨规范的公文语气" }[mode] || "优化表达";
  }

  function resetReviewView() {
    renderFactAudit();
    els.qualityScore.textContent = "—"; els.scoreRing.style.setProperty("--score", 0);
    els.qualityTitle.textContent = "文稿已更新"; els.qualitySummary.textContent = "请重新运行检查，以获取最新结果。";
    els.qualityMetrics.replaceChildren(...["格式规范", "结构完整", "事实一致", "语言精炼"].map((label) => {
      const row = document.createElement("div"); const span = document.createElement("span"); const value = document.createElement("b"); span.textContent = label; value.textContent = "待检"; row.append(span, value); return row;
    }));
    els.issueCount.textContent = "0 条";
    els.issuesList.classList.add("empty");
    els.issuesList.replaceChildren();
    const note = document.createElement("p"); note.textContent = "文稿或材料已有变化，请重新运行质量检查。"; els.issuesList.append(note);
  }

  function openSettings() { closeDrawers(); syncSettingsUI(); openDrawer(els.settingsDrawer); }
  function openHistory() { closeDrawers(); renderHistory(); openDrawer(els.historyDrawer); }

  function restoreAccessToken() {
    try { sessionAccessToken = sessionStorage.getItem(ACCESS_TOKEN_KEY) || ""; }
    catch (_) { sessionAccessToken = ""; }
  }

  function clearAccessToken() {
    sessionAccessToken = "";
    try { sessionStorage.removeItem(ACCESS_TOKEN_KEY); } catch (_) { /* private browsing */ }
  }

  function showAccessGate(message = "请输入访问令牌后继续。") {
    if (!accessTokenRequired || !els.accessModal) return;
    els.accessError.className = "connection-test";
    els.accessError.textContent = message;
    els.accessToken.value = "";
    if (!els.accessModal.open) els.accessModal.showModal();
    window.setTimeout(() => els.accessToken.focus(), 50);
  }

  async function unlockApplication(event) {
    event.preventDefault();
    const token = els.accessToken.value.trim();
    if (!token) {
      els.accessError.className = "connection-test error";
      els.accessError.textContent = "请输入访问令牌。";
      els.accessToken.focus();
      return;
    }
    sessionAccessToken = token;
    setButtonBusy(els.unlockAppButton, true, "正在验证…");
    try {
      await apiRequest("/api/article-sources");
      try { sessionStorage.setItem(ACCESS_TOKEN_KEY, sessionAccessToken); } catch (_) { /* private browsing */ }
      els.accessError.className = "connection-test success";
      els.accessError.textContent = "验证成功，正在进入工作台……";
      await loadMethodologyCatalog(false);
      await loadArticleSources();
      setConnection(true);
      window.setTimeout(() => els.accessModal.close(), 120);
      toast("已进入受保护的工作台", "success");
    } catch (error) {
      clearAccessToken();
      els.accessError.className = "connection-test error";
      els.accessError.textContent = readError(error, "访问令牌验证失败");
      els.accessToken.focus();
    } finally {
      setButtonBusy(els.unlockAppButton, false);
    }
  }

  function updateDeploymentStatus() {
    if (els.accessSettings) els.accessSettings.hidden = !accessTokenRequired;
    if (els.serverProviderCard) els.serverProviderCard.hidden = !serverProvider.configured;
    if (serverProvider.configured && !settings.modelName && serverProvider.defaultModel) {
      els.modelName.placeholder = `服务端默认：${serverProvider.defaultModel}`;
    }
  }

  function openDrawer(drawer) {
    els.drawerBackdrop.hidden = false;
    requestAnimationFrame(() => { els.drawerBackdrop.classList.add("is-visible"); drawer.classList.add("is-open"); drawer.setAttribute("aria-hidden", "false"); });
  }

  function closeDrawers() {
    [els.settingsDrawer, els.historyDrawer].forEach((drawer) => { drawer.classList.remove("is-open"); drawer.setAttribute("aria-hidden", "true"); });
    els.drawerBackdrop.classList.remove("is-visible");
    setTimeout(() => { if (!els.settingsDrawer.classList.contains("is-open") && !els.historyDrawer.classList.contains("is-open")) els.drawerBackdrop.hidden = true; }, 220);
  }

  function syncSettingsUI() {
    const radio = $(`input[name="engineMode"][value="${settings.mode}"]`); if (radio) radio.checked = true;
    els.providerName.value = settings.providerName || "openai";
    els.baseUrl.value = settings.baseUrl || "";
    els.modelName.value = settings.modelName || "";
    els.apiKey.value = sessionApiKey;
    updateSettingsMode();
  }

  function updateSettingsMode() {
    const mode = $('input[name="engineMode"]:checked')?.value || "demo";
    $$('.mode-card').forEach((card) => card.classList.toggle("is-selected", $('input', card).checked));
    els.apiSettings.classList.toggle("is-disabled", mode !== "api");
    $$('input, select, button', els.apiSettings).forEach((control) => { control.disabled = mode !== "api"; });
    if (mode === "api" && serverProvider.configured) {
      els.providerTestStatus.textContent = "服务端模型配置已就绪；页面字段留空即可使用默认配置。";
    }
  }

  async function testProviderConnection() {
    const provider = providerPayloadFromForm();
    if (!provider && !serverProvider.configured) { els.modelName.focus(); toast("请先填写模型名称", "warning"); return; }
    if (provider && !provider.model && !serverProvider.configured) { els.modelName.focus(); toast("请先填写模型名称", "warning"); return; }
    if (provider && els.providerName.value !== "openai" && !provider.base_url && !serverProvider.configured) { els.baseUrl.focus(); toast("请填写该兼容服务的接口地址", "warning"); return; }
    els.providerTestStatus.className = "connection-test";
    els.providerTestStatus.textContent = "正在发送最小连接测试……";
    setButtonBusy(els.testProviderButton, true, "正在测试…");
    try {
      const result = await apiRequest("/api/provider/test", { method: "POST", body: provider ? { provider } : {} });
      els.providerTestStatus.className = "connection-test success";
      els.providerTestStatus.textContent = `${result.message || "连接成功"}${result.meta?.model ? ` · ${result.meta.model}` : ""}`;
    } catch (error) {
      els.providerTestStatus.className = "connection-test error";
      els.providerTestStatus.textContent = readError(error, "连接测试失败");
    } finally { setButtonBusy(els.testProviderButton, false); }
  }

  function resetProviderTestStatus() {
    els.providerTestStatus.className = "connection-test";
    els.providerTestStatus.textContent = "设置已变更，请重新测试连接。";
  }

  function saveSettings() {
    const mode = $('input[name="engineMode"]:checked')?.value || "demo";
    if (mode === "api" && !serverProvider.configured && !els.modelName.value.trim()) { els.modelName.focus(); toast("请填写模型名称", "warning"); return; }
    if (mode === "api" && !serverProvider.configured && els.providerName.value !== "openai" && !els.baseUrl.value.trim()) { els.baseUrl.focus(); toast("请填写该服务商的接口地址", "warning"); return; }
    sessionApiKey = els.apiKey.value.trim();
    settings = { mode, providerName: els.providerName.value, baseUrl: els.baseUrl.value.trim(), modelName: els.modelName.value.trim() };
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch (_) { /* private browsing */ }
    applySettingsStatus(); closeDrawers(); toast(mode === "api" ? "已切换为模型 API" : "已切换为本地演示", "success");
  }

  function restoreSettings() {
    try { settings = { ...settings, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") }; }
    catch (_) { /* ignore corrupted local settings */ }
    delete settings.apiKey;
  }

  function applySettingsStatus() {
    const live = settings.mode === "api";
    els.providerLabel.textContent = live ? (settings.modelName || "模型 API") : "演示引擎";
    els.connectionLabel.textContent = live ? "API 模式" : "本地模式";
    els.connectionDot.classList.toggle("live", live);
  }

  function toggleApiKey() {
    const showing = els.apiKey.type === "text";
    els.apiKey.type = showing ? "password" : "text";
    els.toggleApiKey.textContent = showing ? "显示" : "隐藏";
  }

  function providerPayloadFromForm() {
    if (serverProvider.configured && !els.apiKey.value.trim() && !els.baseUrl.value.trim() && !els.modelName.value.trim()) return undefined;
    const aliases = { deepseek: "openai", qwen: "openai", custom: "openai" };
    return {
      name: aliases[els.providerName.value] || els.providerName.value || "openai",
      model: els.modelName.value.trim() || undefined,
      api_key: els.apiKey.value.trim() || undefined,
      base_url: els.baseUrl.value.trim() || undefined,
    };
  }

  function switchSideTab(button) {
    $$('.panel-tab').forEach((tab) => { const active = tab === button; tab.classList.toggle("is-active", active); tab.setAttribute("aria-selected", String(active)); });
    $$('.tab-content', els.reviewPanel).forEach((panel) => { const active = panel.id === button.dataset.tabPanel; panel.classList.toggle("is-active", active); panel.hidden = !active; });
  }

  function switchMobilePanel(button) {
    $$('.mobile-tab').forEach((tab) => tab.classList.toggle("is-active", tab === button));
    $$('.mobile-panel').forEach((panel) => panel.classList.toggle("is-active", panel.id === button.dataset.mobilePanel));
  }

  function selectTemplate(shouldSave = true) {
    $$('.template-option').forEach((option) => option.classList.toggle("is-selected", $('input', option).checked));
    if (shouldSave) { syncFormState(); scheduleSave(); }
  }

  function selectedTemplate() { return $('input[name="template"]:checked')?.value || "standard"; }

  function updateChecklist(index, checked) {
    appState.checklist[index] = checked;
    els.checkProgress.textContent = `${appState.checklist.filter(Boolean).length}/${appState.checklist.length}`;
    scheduleSave();
  }

  function openBatchModal() {
    const content = documentPlainText();
    if (!content) { toast("请先生成或输入正文", "warning"); return; }
    detectVariables();
    renderBatchPreview();
    els.batchModal.showModal();
    if (!templateVariables().length) toast("请先在标题或正文中加入 {{变量}}", "warning");
  }

  function templateVariables() {
    const source = `${els.documentTitle.value}\n${documentPlainText()}`;
    return [...new Set([...source.matchAll(/\{\{\s*([^{}]+?)\s*\}\}/g)].map((match) => match[1].trim()))];
  }

  function detectVariables() {
    const variables = templateVariables();
    els.variableChips.replaceChildren();
    if (!variables.length) {
      const empty = document.createElement("span"); empty.className = "is-empty"; empty.textContent = "尚未检测到变量"; els.variableChips.append(empty);
      els.batchCsv.placeholder = "先在标题或正文中加入 {{单位}}、{{日期}} 等变量";
      return;
    }
    variables.forEach((name) => { const chip = document.createElement("span"); chip.textContent = name; els.variableChips.append(chip); });
    if (!els.batchCsv.value.trim()) els.batchCsv.placeholder = `${variables.join(",")}\n${variables.map((name) => name === "日期" ? "2026年9月3日" : `示例${name}`).join(",")}`;
  }

  function renderBatchPreview() {
    const rows = parseCsv(els.batchCsv.value);
    const headers = rows[0] || [];
    const data = rows.slice(1).filter((row) => row.some((cell) => cell.trim()));
    const variables = templateVariables();
    const missingHeaders = variables.filter((name) => !headers.includes(name));
    const thead = $('thead', els.batchPreview); const tbody = $('tbody', els.batchPreview);
    thead.replaceChildren(); tbody.replaceChildren();
    if (headers.length) {
      const tr = document.createElement("tr"); headers.forEach((cell) => { const th = document.createElement("th"); th.textContent = cell; tr.append(th); }); thead.append(tr);
      data.slice(0, 6).forEach((row) => { const line = document.createElement("tr"); headers.forEach((_, index) => { const td = document.createElement("td"); td.textContent = row[index] || ""; line.append(td); }); tbody.append(line); });
    }
    els.batchEmpty.hidden = Boolean(headers.length && data.length);
    els.batchRowCount.textContent = `${data.length} 行`;
    const ready = Boolean(variables.length && headers.length && data.length && !missingHeaders.length);
    els.generateBatchButton.disabled = !ready;
    if (!variables.length) els.batchValidation.textContent = "请先在文稿中加入 {{变量}}";
    else if (missingHeaders.length) els.batchValidation.textContent = `CSV 缺少列：${missingHeaders.join("、")}`;
    else els.batchValidation.textContent = data.length ? `将生成 ${data.length} 份 Word 文稿` : "请先填写批量数据";
  }

  async function importBatchFile() {
    const file = els.batchFile.files?.[0]; if (!file) return;
    try { els.batchCsv.value = await file.text(); renderBatchPreview(); toast("批量数据已读取", "success"); }
    catch (_) { toast("CSV 文件读取失败", "error"); }
    finally { els.batchFile.value = ""; }
  }

  async function exportBatch() {
    const parsed = parseCsv(els.batchCsv.value); const headers = parsed[0] || [];
    const rows = parsed.slice(1).filter((row) => row.some((cell) => cell.trim())).map((row) => Object.fromEntries(headers.map((header, index) => [header, row[index] || ""])));
    if (!rows.length) return;
    setButtonBusy(els.generateBatchButton, true, "正在生成…");
    try {
      const base = safeFilename(els.batchFilename.value || "公文批量文件"); const filename = `${base}.zip`;
      const response = await fetch("/api/export/batch-docx", { method: "POST", headers: requestHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ template: { title: els.documentTitle.value.trim() || "公文", content: documentPlainText(), template_style: selectedTemplate(), metadata: { document_type: els.documentType.value, issuing_org: els.issuingOrg.value.trim(), issue_date: els.issueDate.value } }, rows, filename }) });
      if (!response.ok) throw await responseError(response);
      downloadBlob(await response.blob(), filename); els.batchModal.close(); toast(`${rows.length} 份文稿已生成`, "success");
    } catch (error) { toast(readError(error, "批量导出失败"), "error"); }
    finally { setButtonBusy(els.generateBatchButton, false); renderBatchPreview(); }
  }

  function parseCsv(text) {
    text = String(text || "").replace(/^\uFEFF/, "");
    const rows = []; let row = []; let cell = ""; let quoted = false;
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index]; const next = text[index + 1];
      if (char === '"' && quoted && next === '"') { cell += '"'; index += 1; }
      else if (char === '"') quoted = !quoted;
      else if (char === "," && !quoted) { row.push(cell.trim()); cell = ""; }
      else if ((char === "\n" || char === "\r") && !quoted) { if (char === "\r" && next === "\n") index += 1; row.push(cell.trim()); if (row.some(Boolean)) rows.push(row); row = []; cell = ""; }
      else cell += char;
    }
    row.push(cell.trim()); if (row.some(Boolean)) rows.push(row);
    return rows;
  }

  function scheduleSave() {
    els.saveStatus.textContent = "正在保存…"; els.saveDot.classList.add("saving");
    clearTimeout(saveTimer); saveTimer = window.setTimeout(persistState, 650);
  }

  function persistState() {
    syncFormState();
    appState.document.title = els.documentTitle.value;
    appState.document.html = sanitizeHtml(els.documentEditor.innerHTML);
    appState.updatedAt = Date.now();
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(appState));
      els.saveStatus.textContent = "所有更改已保存"; els.saveDot.classList.remove("saving");
    } catch (_) { els.saveStatus.textContent = "浏览器存储空间不足"; }
  }

  function restoreState() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (saved && typeof saved === "object") {
        const defaults = freshState();
        appState = { ...defaults, ...saved, form: { ...defaults.form, ...(saved.form || {}) }, document: { ...defaults.document, ...(saved.document || {}) }, exportMeta: { ...defaults.exportMeta, ...(saved.exportMeta || {}) } };
        appState.styleReferences = Array.isArray(saved.styleReferences) ? saved.styleReferences.map(normalizeArticleReference).filter((item) => item.id).slice(0, 8) : [];
        appState.checklist = Array.from({ length: 6 }, (_, index) => Boolean(Array.isArray(saved.checklist) && saved.checklist[index]));
        appState.serverDocumentId = typeof saved.serverDocumentId === "string" ? saved.serverDocumentId : "";
        appState.serverDocumentVersion = Math.max(0, Number(saved.serverDocumentVersion) || 0);
      }
    } catch (_) { appState = freshState(); }
  }

  function applyStateToUI() {
    const form = appState.form;
    els.documentType.value = form.document_type; els.topic.value = form.topic; els.purpose.value = form.purpose;
    els.audience.value = form.audience; els.referenceStyle.value = form.reference_style || "权威媒体综合写法"; els.length.value = normalizeLength(form.length); els.requirements.value = form.requirements;
    els.materials.value = form.materials; els.factLock.checked = form.factLock !== false;
    els.titleCount.value = String(Math.max(1, Math.min(20, Number(form.title_count) || 5)));
    const savedCustomMethod = form.custom_methodology && typeof form.custom_methodology === "object" ? form.custom_methodology : null;
    els.customMethodologyName.value = String(savedCustomMethod?.name || "");
    els.customMethodologySteps.value = Array.isArray(savedCustomMethod?.steps) ? savedCustomMethod.steps.join("\n") : "";
    if (savedCustomMethod) els.customMethodologyDetails.open = true;
    const savedCustomTitle = form.custom_title_formula && typeof form.custom_title_formula === "object" ? form.custom_title_formula : null;
    els.customTitleFormulaName.value = String(savedCustomTitle?.name || "");
    els.customTitleFormulaTemplate.value = String(savedCustomTitle?.template || (typeof form.custom_title_formula === "string" ? form.custom_title_formula : ""));
    els.customTitleFormulaRule.value = String(savedCustomTitle?.rule || "");
    if (els.customTitleFormulaTemplate.value) els.customTitleFormulaDetails.open = true;
    const tone = $(`input[name="tone"][value="${cssEscape(form.tone)}"]`); if (tone) tone.checked = true;
    els.issuingOrg.value = appState.exportMeta.issuingOrg || ""; els.issueDate.value = appState.exportMeta.issueDate || localDateValue();
    const template = $(`input[name="template"][value="${cssEscape(appState.exportMeta.template || "standard")}"]`); if (template) template.checked = true; selectTemplate(false);
    els.documentBadge.textContent = form.document_type; els.paperType.textContent = form.document_type;
    els.serverDocumentStatus.textContent = appState.serverDocumentId ? `已关联 · 第 ${appState.serverDocumentVersion || 1} 版` : "尚未保存到服务端";
    els.documentTitle.value = appState.document.title || "";
    if (appState.document.html) {
      els.documentEditor.innerHTML = sanitizeHtml(appState.document.html || "");
      els.generationHero.classList.add("is-hidden"); els.documentWorkspace.classList.remove("is-hidden");
      renderOutline();
    }
    renderCandidates();
    $$('.checklist input').forEach((checkbox, index) => { checkbox.checked = Boolean(appState.checklist[index]); });
    els.checkProgress.textContent = `${appState.checklist.filter(Boolean).length}/${appState.checklist.length}`;
    renderReview(); renderFactAudit(); renderSelectedReferences(); applySettingsStatus();
  }

  function createSnapshot(label, notify) {
    persistState();
    try {
      const history = loadHistory();
      const last = history[0];
      const snapshot = { id: Date.now(), label, title: appState.document.title || appState.form.topic || "未命名文稿", createdAt: Date.now(), state: structuredCloneSafe(appState) };
      if (!last || last.state?.document?.html !== snapshot.state.document.html || notify) history.unshift(snapshot);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)));
      if (notify) { renderHistory(); toast("当前版本已保存", "success"); }
    } catch (_) { if (notify) toast("版本保存未完成", "error"); }
  }

  function loadHistory() { try { const value = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); return Array.isArray(value) ? value : []; } catch (_) { return []; } }

  function renderHistory() {
    const history = loadHistory(); els.historyList.replaceChildren();
    if (!history.length) { const empty = document.createElement("div"); empty.className = "history-empty"; empty.textContent = "还没有版本记录。生成初稿或手动保存后，会在这里显示。"; els.historyList.append(empty); return; }
    history.forEach((item, index) => {
      const article = document.createElement("article"); article.className = "history-item";
      const marker = document.createElement("i"); const copy = document.createElement("div");
      const label = document.createElement("span"); label.textContent = index === 0 ? "最新" : item.label || "自动保存";
      const title = document.createElement("strong"); title.textContent = item.title || "未命名文稿";
      const time = document.createElement("small"); time.textContent = formatDateTime(item.createdAt);
      copy.append(label, title, time);
      const restore = document.createElement("button"); restore.type = "button"; restore.textContent = "恢复"; restore.addEventListener("click", () => restoreSnapshot(item));
      article.append(marker, copy, restore); els.historyList.append(article);
    });
  }

  function restoreSnapshot(snapshot) {
    if (!snapshot.state) return;
    appState = { ...freshState(), ...structuredCloneSafe(snapshot.state) };
    applyStateToUI(); persistState(); closeDrawers(); toast("已恢复所选版本", "success");
  }

  function handleKeyboard(event) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); generateDocument(); }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") { event.preventDefault(); createSnapshot("手动保存的版本", true); }
    if (event.key === "Escape") hideSelectionToolbar();
  }

  function documentPlainText() {
    return (els.documentEditor?.innerText || "").replace(/\u00a0/g, " ").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function sanitizeHtml(html) {
    const source = document.createElement("template"); source.innerHTML = String(html || "");
    const output = document.createElement("div");
    const allowed = new Set(["P", "H2", "H3", "STRONG", "B", "UL", "OL", "LI", "BR", "EM"]);
    const copy = (node, parent) => {
      if (node.nodeType === Node.TEXT_NODE) { parent.append(document.createTextNode(node.textContent || "")); return; }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      if (["SCRIPT", "STYLE", "IFRAME", "OBJECT", "EMBED", "LINK", "META"].includes(node.tagName)) return;
      if (!allowed.has(node.tagName)) { [...node.childNodes].forEach((child) => copy(child, parent)); return; }
      const clean = document.createElement(node.tagName.toLowerCase());
      [...node.childNodes].forEach((child) => copy(child, clean)); parent.append(clean);
    };
    [...source.content.childNodes].forEach((node) => copy(node, output));
    return output.innerHTML;
  }

  function replaceOptions(select, values) {
    const current = select.value; const fragment = document.createDocumentFragment();
    values.forEach((item) => {
      const value = typeof item === "string" ? item : String(item.value || item.id || item.name || "");
      if (!value) return;
      const option = document.createElement("option"); option.value = value; option.textContent = typeof item === "string" ? item : String(item.label || item.name || value); fragment.append(option);
    });
    if (fragment.childNodes.length) { select.replaceChildren(fragment); if ([...select.options].some((option) => option.value === current)) select.value = current; }
  }

  function setConnection(connected) {
    els.connectionDot.classList.toggle("connected", connected);
    if (!connected && settings.mode === "demo") els.connectionLabel.textContent = "服务未连接";
  }

  function showLoading(title, message) {
    els.loadingTitle.textContent = title; els.loadingMessage.textContent = message;
    els.loadingOverlay.hidden = false; document.body.classList.add("is-loading");
  }

  function hideLoading() { els.loadingOverlay.hidden = true; document.body.classList.remove("is-loading"); }

  function setButtonBusy(button, busy, label = "处理中…") {
    if (!button) return;
    if (busy) { if (!button.dataset.originalHtml) button.dataset.originalHtml = button.innerHTML; button.disabled = true; button.textContent = label; }
    else { button.disabled = false; if (button.dataset.originalHtml) { button.innerHTML = button.dataset.originalHtml; delete button.dataset.originalHtml; } }
  }

  function toast(message, type = "info") {
    let region = $(".toast-region");
    if (!region) { region = document.createElement("div"); region.className = "toast-region"; region.setAttribute("aria-live", "polite"); document.body.append(region); }
    const item = document.createElement("div"); item.className = `toast ${type}`;
    const icon = document.createElement("span"); icon.textContent = type === "success" ? "✓" : type === "error" ? "!" : type === "warning" ? "!" : "i";
    const copy = document.createElement("p"); copy.textContent = String(message || "操作完成");
    item.append(icon, copy); region.append(item);
    requestAnimationFrame(() => item.classList.add("is-visible"));
    setTimeout(() => { item.classList.remove("is-visible"); setTimeout(() => item.remove(), 240); }, 3600);
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function safeFilename(value) { return String(value).replace(/[\\/:*?"<>|\r\n]+/g, "-").replace(/\s+/g, " ").trim().slice(0, 80) || "公文"; }
  function countChinese(value) { return String(value || "").replace(/\s/g, "").length; }
  function normalizeLength(value) { const text = String(value || "标准"); return ["精简", "标准", "详细"].find((item) => text.startsWith(item)) || "标准"; }
  function localDateValue() { const date = new Date(); const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000); return local.toISOString().slice(0, 10); }
  function formatDateTime(timestamp) { return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(timestamp)); }
  function chineseNumber(value) { return ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"][value] || String(value); }
  function cssEscape(value) { return window.CSS?.escape ? CSS.escape(String(value)) : String(value).replace(/["\\]/g, "\\$&"); }
  function structuredCloneSafe(value) { return typeof structuredClone === "function" ? structuredClone(value) : JSON.parse(JSON.stringify(value)); }

})();
