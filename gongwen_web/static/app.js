(() => {
  "use strict";

  const STORAGE_KEY = "yanzhang.demo.document.v1";
  const SETTINGS_KEY = "yanzhang.demo.settings.v1";
  const HISTORY_KEY = "yanzhang.demo.history.v1";
  const ACCESS_TOKEN_KEY = "yanzhang.access-token.v1";
  const PHASE2_KEY = "yanzhang.workspace.phase2.v1";
  const MAX_HISTORY = 12;
  const responseValidators = globalThis.YanzhangResponseValidators;
  if (!responseValidators) throw new Error("响应校验模块未加载");
  const PAGE_SIZE = 100;
  const MAX_PAGE_COUNT = 100;
  const MAX_ACADEMIC_RECORDS = 1_000;
  const MAX_ACADEMIC_EVIDENCE = 1_000;
  const workspaceContext = globalThis.YanzhangWorkspaceContext;
  if (!workspaceContext) throw new Error("写作任务上下文模块未加载");
  const RECIPE_CATALOG = workspaceContext.RECIPE_CATALOG;
  const scenarioCatalog = globalThis.YanzhangScenarioCatalog;
  const scenarioWorkspace = globalThis.YanzhangScenarioWorkspace;
  if (!scenarioCatalog || !scenarioWorkspace) throw new Error("场景工作台未加载");
  const executionMode = globalThis.YanzhangExecutionMode;
  if (!executionMode) throw new Error("生成方式说明模块未加载");

  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];

  const els = {};
  let appState = freshState();
  let settings = { mode: "demo", providerName: "openai", baseUrl: "", modelName: "" };
  let sessionApiKey = "";
  let modelSettingsSerial = 0;
  let serviceConnected = null;
  let providerTestSerial = 0;
  let drawerReturnFocus = null;
  let sessionAccessToken = "";
  let accessTokenRequired = false;
  let serverProvider = { configured: false, providerName: "", defaultModel: "" };
  let savedSelection = null;
  let saveTimer = 0;
  let factTimer = 0;
  let catalogRequestSerial = 0;
  let projectListRequestSerial = 0;
  let generationRequestSerial = 0;
  let expressionRequestSerial = 0;
  let serverDocumentSaveSerial = 0;
  let methodologyCatalog = { titleFormulas: [], contentMethodologies: [], defaults: [] };
  let methodologyCatalogReady = false;
  let phase2State = freshPhase2State();
  let phase2SaveTimer = 0;
  let v2ServiceState = "checking";
  let projectAssetsLoading = false;
  let projectSwitchSerial = 0;
  let projectRequestController = new AbortController();

  document.addEventListener("DOMContentLoaded", init);

  function freshState() {
    return {
      form: {
        document_type: "实施方案", topic: "", purpose: "", audience: "", tone: "严谨规范",
        reference_style: "权威媒体综合写法", length: "标准", requirements: "", materials: "", factLock: true,
        content_methodology_id: "", custom_methodology: null, title_formula_ids: [], title_count: 5,
        custom_title_formula: null,
      },
      document: { title: "", html: "", candidates: [], outline: [], execution: null, title_execution: null },
      review: null,
      scenarioId: "gongwen",
      scenarioPreferences: {},
      styleCustom: false,
      factAudit: null,
      styleReferences: [],
      serverDocumentId: "",
      serverDocumentVersion: 0,
      checklist: [false, false, false, false, false, false],
      exportMeta: { issuingOrg: "", issueDate: localDateValue(), template: "standard" },
      updatedAt: Date.now(),
    };
  }

  function freshPhase2State() {
    return {
      view: "home",
      local_draft_mode: true,
      project_id: "",
      project_name: "",
      project_source: "",
      standalone_document: false,
      projects: [],
      project_drafts: {},
      brief: {
        id: "", content_type: "official-document", channel: "document", deadline: "",
        target_language: "zh-CN", keywords: "", constraints: "", saved_at: "", payload_hash: "",
        scenario_pack_id: "gongwen", recipe_id: "implementation-plan",
      },
      expression: { focus: "title", instruction: "", count: 5, results: [] },
      selected_title: "",
      master_asset_id: "",
      master_asset_revision: null,
      output_binding_hash: "",
      document_stale: false,
      workflow_id: "",
      workflow_status: "",
      material_ids: [],
      variants: [],
      academic: {
        task_type: "literature-review", title: "", goal: "", citation_style: "gb-t-7714",
        import_format: "bibtex", import_content: "", records: [], matrix: [], evidence: [],
        evidence_record_id: "", evidence_query: "", evidence_text: "", claims_text: "",
        claims: [], claims_dirty: false, recovered_claims: [], recovered_claim_links: [],
        claim_links: [], claim_comments: [], coverage: null, citations: [], outline: null,
        reviewer_comments: "", manuscript_changes: "", rebuttal: [], integrity: null,
      },
    };
  }

  async function init() {
    cacheElements();
    restoreSettings();
    restoreAccessToken();
    restoreState();
    restorePhase2State();
    bindEvents();
    applyStateToUI();
    applyPhase2StateToUI();
    initializeCollectionDates();
    updateCounts();
    updateFacts();
    const ready = await bootstrap();
    if (ready) await loadArticleSources();
    void initializePhase2Service();
  }

  function cacheElements() {
    [
      "saveDot", "saveStatus", "historyButton", "serverDocumentsButton", "focusButton", "settingsButton", "quickExportButton",
      "engineBanner", "engineBannerTitle", "engineBannerDetail", "engineBannerButton", "retryConnectionButton",
      "documentExecution", "titleExecution", "serverProviderTitle", "serverProviderDetail",
      "appShell", "scenarioOverview", "scenarioName", "scenarioDescription", "scenarioCapabilities", "toneSelector",
      "topicLabel", "purposeLabel", "audienceLabel", "materialsLabel", "requirementsLabel", "keywordsLabel",
      "referenceStyleLabel", "materialSectionLabel", "referenceStyleDescription", "referencePickerTitle", "referencePickerDescription",
      "openProjectMaterialsButton", "openAcademicReferencesButton", "sceneEvidenceNote", "generateButtonLabel",
      "knowledgeItemLabel", "knowledgeSelectedLabel", "knowledgeFactLabel", "reviewSceneDescription", "deliverySceneNote",
      "hubFormatLabel", "hubStructureLabel", "hubFactLabel", "hubLanguageLabel", "hubCitationLabel",
      "inputPanel", "writingPanel", "reviewPanel", "writingForm", "loadExampleButton", "documentType",
      "length", "topic", "topicCount", "purpose", "audience", "referenceStyle", "requirements", "clearRequirements",
      "materials", "materialCount", "materialFile", "uploadMaterialButton", "materialFileName",
      "extractFactsButton", "factGroups", "factHint", "factLock", "documentBadge", "wordCount",
      "readingTime", "undoButton", "redoButton", "regenerateButton", "serverLibraryButton", "copyButton", "insertFieldButton", "generationHero", "generateButton",
      "documentWorkspace", "titleCandidates", "refreshTitlesButton", "documentTitle", "documentEditor", "documentContextStatus",
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
      "suiteNav", "routeStage", "homePage", "projectsPage", "knowledgePage", "recipesPage",
      "reviewHubPage", "deliveryPage", "academicPage", "settingsPage", "homeBriefPreview",
      "v2CapabilityState", "projectSelect", "refreshProjectsButton", "createProjectButton",
      "projectContextStatus", "projectModal", "projectForm", "newProjectName",
      "newProjectDescription", "newProjectScenarioPack", "projectCreateStatus", "submitProjectButton",
      "briefCard", "briefCompletion", "briefContentType", "briefChannel", "briefScenarioPack", "briefRecipe",
      "briefDeadline", "briefLanguage", "briefKeywords", "briefConstraints", "briefStatus",
      "normalizeBriefButton", "runProjectWorkflowButton", "projectWorkflowStatus",
      "expressionLab", "expressionFocusTabs", "expressionInstruction",
      "expressionCount", "generateExpressionsButton", "expressionResults", "variantStudio",
      "variantSourceStatus", "variantChannels", "variantLength", "variantInstruction",
      "generateVariantsButton", "variantResults", "knowledgeOpenLibraryButton", "knowledgeCollectButton",
      "knowledgeServerButton", "knowledgeItemCount", "knowledgeSelectedCount", "knowledgeFactCount",
      "knowledgeSearch", "knowledgeKind", "searchKnowledgeButton", "knowledgeResults",
      "projectMaterialComposer", "projectMaterialTitle", "projectMaterialKind",
      "projectMaterialContent", "projectMaterialUrl", "projectMaterialStatus", "addProjectMaterialButton",
      "refreshRecipesButton", "recipeCatalog", "hubRunReviewButton", "hubScoreRing",
      "hubQualityScore", "reviewHubStatus", "reviewHubSummary", "hubFormatScore",
      "hubStructureScore", "hubFactScore", "hubLanguageScore", "hubCitationScore",
      "academicIntegrityResult", "academicIntegrityStatus", "academicIntegritySummary",
      "deliveryWordButton", "deliveryWordSecondaryButton", "deliveryBatchButton", "deliveryPrintButton",
      "deliveryVariantsButton", "deliveryAssetTitle", "deliveryAssetMeta", "academicTaskType",
      "academicTitle", "academicGoal", "academicCitationStyle", "academicReferenceCount",
      "academicImportFormat", "academicImportContent", "academicImportButton", "academicRecords",
      "academicFormatCitationsButton", "academicCitationOutput", "academicMatrixButton",
      "academicMatrixBody", "academicCoverage", "academicEvidenceRecord", "academicEvidenceQuery",
      "academicEvidenceText", "academicExtractEvidenceButton", "academicEvidenceSnippets",
      "academicClaims", "academicVerifyClaimsButton", "academicClaimLinks", "academicOutlineButton",
      "academicOutline", "academicReviewerComments", "academicManuscriptChanges", "academicRebuttalButton",
      "academicRebuttalOutput", "openSettingsDrawerButton", "settingsEngineTitle", "settingsEngineSummary",
      "settingsEngineButton", "settingsV2Title", "settingsV2Summary", "probeV2Button",
      "clearPhase2DraftsButton", "clearAllLocalDataButton", "localDraftMode",
    ].forEach((id) => { if (document.getElementById(id)) els[id] = document.getElementById(id); });
  }

  function currentScenario() {
    return scenarioWorkspace.profile(phase2State.brief.scenario_pack_id || appState.scenarioId);
  }

  function selectedStyleDescription() {
    return currentScenario().styles.find((item) => item.label === els.referenceStyle.value)?.description || "";
  }

  function updateReferenceStyleDescription() {
    els.referenceStyleDescription.textContent = selectedStyleDescription();
  }

  function renderScenarioControls(scene, values = {}) {
    els.appShell.dataset.scenario = scene.id;
    els.scenarioOverview.dataset.scenario = scene.id;
    els.inputPanel.dataset.scenario = scene.id;
    els.scenarioName.textContent = scene.name;
    els.scenarioDescription.textContent = scene.description;
    els.scenarioCapabilities.textContent = `${scene.styles.length} 种表达方法 · ${scenarioCatalog.recipes[scene.id].length} 个写作配方 · 独立材料与审校标准`;
    els.referenceStyle.replaceChildren(...scene.styles.map((style) => makeOption(style.label, style.label)));
    els.referenceStyle.value = scene.styles.some((style) => style.label === values.reference_style) ? values.reference_style : scene.default_style;
    els.toneSelector.replaceChildren(...scene.tones.map((tone) => {
      const label = document.createElement("label");
      const input = document.createElement("input"); input.type = "radio"; input.name = "tone"; input.value = tone;
      input.checked = tone === (scene.tones.includes(values.tone) ? values.tone : scene.default_tone);
      input.addEventListener("change", handleFormInput);
      const text = document.createElement("span"); text.textContent = tone; label.append(input, text); return label;
    }));
    const labelIds = { topic: "topicLabel", purpose: "purposeLabel", audience: "audienceLabel", materials: "materialsLabel", requirements: "requirementsLabel", keywords: "keywordsLabel", reference_style: "referenceStyleLabel" };
    Object.entries(labelIds).forEach(([key, id]) => { els[id].textContent = scene.labels[key]; });
    const fieldIds = { topic: "topic", purpose: "purpose", audience: "audience", materials: "materials", requirements: "requirements", keywords: "briefKeywords" };
    Object.entries(fieldIds).forEach(([key, id]) => { els[id].placeholder = scene.placeholders[key]; });
    els.materialSectionLabel.textContent = scene.labels.materials;
    els.generateButtonLabel.textContent = scene.labels.generate;
    els.referencePickerTitle.textContent = scene.source.title;
    els.referencePickerDescription.textContent = scene.source.description;
    els.openArticleLibraryButton.textContent = scene.source.action_label;
    els.openProjectMaterialsButton.hidden = scene.source.action === "materials";
    // Academic tools are entered through the academic scene, not advertised as
    // a workplace style-reference shortcut.
    els.openAcademicReferencesButton.hidden = true;
    els.selectedReferences.hidden = scene.id !== "gongwen";
    els.sceneEvidenceNote.hidden = false;
    els.sceneEvidenceNote.textContent = scene.id === "academic"
      ? "文献元数据不是原文证据。已导入的文献和可定位片段会参与本场景成文；无证据时只给结构与待补项，不编造结论。"
      : "内置写法是原创结构方法，不是已抓取的范文。项目事实、历史样文与外部写法参考分开管理；换场景会暂存当前输入，不自动混用。";
    scene.checklist.forEach((label, index) => { const element = document.getElementById(`checklistLabel${index}`); if (element) element.textContent = label; });
    const reviewDescriptions = {
      gongwen: ["文档类型、层级、称谓与日期", "逻辑、标题、段首与衔接", "数字、主体、时间与出处", "赘词、歧义与表达力度"],
      workplace: ["结论、沟通请求与决策要点", "背景、依据、选项与下一步", "记录、估算与承诺依据", "动作、负责人、期限与待确认项"],
      media: ["读者关切、信息重点与受众", "导语、背景、展开与收束", "事实、引语、消息源与核验", "篇幅、媒介形式与发布要求"],
      academic: ["研究问题、概念与论证边界", "研究结构、方法与材料范围", "主张、原文证据与引用定位", "术语一致、审慎措辞与推断边界"],
    };
    ["hubFormatLabel", "hubStructureLabel", "hubFactLabel", "hubLanguageLabel"].forEach((id, index) => {
      if (!els[id]) return;
      els[id].textContent = scene.review_dimensions[index];
      if (els[id].nextElementSibling) els[id].nextElementSibling.textContent = reviewDescriptions[scene.id][index];
    });
    if (els.hubCitationLabel) els.hubCitationLabel.textContent = scene.id === "academic" ? "引文与证据" : "来源溯源";
    if (els.reviewSceneDescription) els.reviewSceneDescription.textContent = `${scene.name}：${scene.checklist.slice(0, 4).join("；")}。自动检查仅作辅助，未运行的维度不会显示为已通过。`;
    if (els.deliverySceneNote) els.deliverySceneNote.textContent = scene.id === "academic"
      ? "导出为可编辑通用 Word；参考文献可先追加到母稿。期刊专用版式、参考文献管理器域和投稿规范仍需按期刊要求核对。"
      : scene.id === "workplace" ? "邮件、周报与方案可复制或导出为通用 Word；演示提纲为文字内容，不冒充已生成 PPT 文件。" : "导出当前母稿及已采用内容；渠道变体保留母稿来源，发布前核对格式和事实。";
    if (els.knowledgeItemLabel) els.knowledgeItemLabel.textContent = "当前项目材料";
    if (els.knowledgeSelectedLabel) els.knowledgeSelectedLabel.textContent = scene.id === "academic" ? "已导入文献" : "本场景写法样本";
    if (els.knowledgeFactLabel) els.knowledgeFactLabel.textContent = scene.id === "academic" ? "原文证据片段" : "本场景事实卡";
    els.knowledgeOpenLibraryButton.textContent = scene.source.action_label;
    els.projectMaterialTitle.placeholder = `${scene.name} · 原始记录或材料标题`;
    els.projectMaterialContent.placeholder = scene.placeholders.materials;
    els.academicIntegrityResult.hidden = scene.id !== "academic";
    updateReferenceStyleDescription();
  }

  function applyScenarioProfile(context) {
    const from = appState.scenarioId || scenarioWorkspace.inferScenario(appState.form.document_type);
    const to = context.scenarioPackId;
    const current = {
      topic: els.topic.value, purpose: els.purpose.value, audience: els.audience.value,
      materials: els.materials.value, requirements: els.requirements.value,
      keywords: els.briefKeywords.value, constraints: els.briefConstraints.value,
      reference_style: els.referenceStyle.value || appState.form.reference_style,
      tone: $('input[name="tone"]:checked')?.value || appState.form.tone,
      style_custom: appState.styleCustom, styleReferences: appState.styleReferences,
      material_ids: phase2State.material_ids,
    };
    const transition = scenarioWorkspace.transition({ from, to, recipeId: context.recipeId, preferences: appState.scenarioPreferences, current });
    appState.scenarioPreferences = transition.preferences;
    appState.scenarioId = to;
    appState.styleCustom = transition.values.style_custom;
    if (from !== to) {
      ["topic", "purpose", "audience", "materials", "requirements"].forEach((key) => { els[key].value = transition.values[key] || ""; });
      els.briefKeywords.value = transition.values.keywords || "";
      els.briefConstraints.value = transition.values.constraints || "";
      phase2State.material_ids = Array.isArray(transition.values.material_ids) ? transition.values.material_ids : [];
    }
    appState.styleReferences = transition.values.styleReferences;
    renderScenarioControls(currentScenario(), transition.values);
    renderSelectedReferences();
    renderSceneRecipes();
    selectExpressionFocus(phase2State.expression.focus || "title", false);
    updateFacts();
  }

  function activateScenario(packId) {
    if (!scenarioCatalog.profiles[packId]) return false;
    if (phase2State.brief.scenario_pack_id === packId) return true;
    els.briefScenarioPack.value = packId;
    reconcileTaskContext("scenario_pack");
    return true;
  }

  function openProjectMaterials() {
    openSuiteView("knowledge", { focusId: "projectMaterialComposer", openDetails: true });
  }

  function openScenarioReferences() {
    const action = currentScenario().source.action;
    if (action === "academic") { openSuiteView("academic", { focusId: "academicImportContent" }); return; }
    if (action === "materials") { openProjectMaterials(); return; }
    openArticleLibrary();
  }

  function currentFactualMaterialText() {
    return [els.materials.value.trim(), currentScenario().id === "academic" ? scenarioWorkspace.academicMaterials(phase2State.academic) : ""].filter(Boolean).join("\n\n");
  }

  function renderSceneRecipes() {
    els.recipeCatalog.replaceChildren();
    const active = currentScenario().id;
    const order = [active, ...Object.keys(scenarioCatalog.profiles).filter((id) => id !== active)];
    order.forEach((packId) => scenarioCatalog.recipes[packId].forEach((recipe) => {
      const article = document.createElement("article"); article.className = `recipe-card${packId === active ? " is-featured" : ""}`;
      article.dataset.recipeId = recipe.id;
      const top = document.createElement("div"); top.className = "recipe-card-top";
      const category = document.createElement("span"); category.textContent = scenarioCatalog.profiles[packId].name;
      const badge = document.createElement("b"); badge.textContent = recipe.id === phase2State.brief.recipe_id ? "当前配方" : "内置配方"; top.append(category, badge);
      const title = document.createElement("h2"); title.textContent = recipe.name;
      const summary = document.createElement("p"); summary.textContent = recipe.summary;
      const list = document.createElement("ol"); recipe.sections.forEach((section) => { const li = document.createElement("li"); li.textContent = section.title; list.append(li); });
      const button = document.createElement("button"); button.type = "button"; button.className = "secondary-button"; button.textContent = "采用此配方";
      button.addEventListener("click", () => applyRecipe(recipe.id));
      article.append(top, title, summary, list, button); els.recipeCatalog.append(article);
    }));
  }

  function bindEvents() {
    const formInputs = $$('input:not([type="file"]), textarea, select', els.writingForm);
    const specializedFormControls = new Set([
      "contentMethodology", "customMethodologyName", "customMethodologySteps",
      "customTitleFormulaName", "customTitleFormulaTemplate", "customTitleFormulaRule", "titleCount",
    ]);
    formInputs.filter((input) => !specializedFormControls.has(input.id)).forEach((input) => {
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
    els.contentMethodology.addEventListener("change", handleMethodologyChange);
    [els.customMethodologyName, els.customMethodologySteps, els.customTitleFormulaName, els.customTitleFormulaTemplate, els.customTitleFormulaRule, els.titleCount]
      .forEach((control) => {
        const handler = control === els.customMethodologyName || control === els.customMethodologySteps
          ? handleMethodologyChange
          : () => { syncFormState(); scheduleSave(); };
        control.addEventListener("input", handler);
        control.addEventListener("change", handler);
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
    els.engineBannerButton.addEventListener("click", openSettings);
    els.retryConnectionButton.addEventListener("click", retryServiceConnection);
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
    els.openArticleLibraryButton.addEventListener("click", openScenarioReferences);
    els.openProjectMaterialsButton.addEventListener("click", openProjectMaterials);
    els.openAcademicReferencesButton.addEventListener("click", () => { activateScenario("academic"); openSuiteView("academic"); });
    els.referenceStyle.addEventListener("change", () => { appState.styleCustom = true; updateReferenceStyleDescription(); });
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

    $$("[data-suite-view]").forEach((button) => button.addEventListener("click", () => openSuiteView(button.dataset.suiteView)));
    $$("[data-open-view]").forEach((button) => button.addEventListener("click", () => {
      if (button.dataset.openView === "academic") activateScenario("academic");
      openSuiteView(button.dataset.openView, { focusId: button.dataset.projectFocus || "" });
    }));
    $(".brand")?.addEventListener("click", (event) => { event.preventDefault(); openSuiteView("home"); });

    [els.briefChannel, els.briefDeadline, els.briefLanguage, els.briefKeywords, els.briefConstraints]
      .forEach((control) => {
        control.addEventListener("input", handlePhase2Input);
        control.addEventListener("change", handlePhase2Input);
      });
    els.briefContentType.addEventListener("change", () => reconcileTaskContext("content_type"));
    els.briefScenarioPack.addEventListener("change", () => reconcileTaskContext("scenario_pack"));
    els.briefRecipe.addEventListener("change", () => reconcileTaskContext("recipe"));
    els.normalizeBriefButton.addEventListener("click", normalizeBrief);
    els.runProjectWorkflowButton.addEventListener("click", runProjectWorkflow);
    $$("[data-expression-focus]").forEach((button) => button.addEventListener("click", () => selectExpressionFocus(button.dataset.expressionFocus)));
    [els.expressionInstruction, els.expressionCount].forEach((control) => {
      control.addEventListener("input", handlePhase2Input);
      control.addEventListener("change", handlePhase2Input);
    });
    els.generateExpressionsButton.addEventListener("click", generateExpressions);
    $$('input[type="checkbox"]', els.variantChannels).forEach((control) => control.addEventListener("change", handlePhase2Input));
    [els.variantLength, els.variantInstruction].forEach((control) => {
      control.addEventListener("input", handlePhase2Input);
      control.addEventListener("change", handlePhase2Input);
    });
    els.generateVariantsButton.addEventListener("click", generateVariants);

    els.knowledgeOpenLibraryButton.addEventListener("click", openScenarioReferences);
    els.knowledgeCollectButton.addEventListener("click", () => {
      openArticleLibrary();
      window.setTimeout(() => els.collectKeywords?.focus(), 80);
    });
    els.knowledgeServerButton.addEventListener("click", openServerDocuments);
    els.searchKnowledgeButton.addEventListener("click", searchKnowledge);
    els.knowledgeSearch.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); searchKnowledge(); }
    });
    els.refreshRecipesButton.addEventListener("click", () => loadWorkflowDefinitions(true));
    $$('[data-apply-recipe]').forEach((button) => button.addEventListener("click", () => applyRecipe(button.dataset.applyRecipe)));
    els.hubRunReviewButton.addEventListener("click", runProjectReview);

    els.deliveryWordButton.addEventListener("click", () => exportProjectAsset("docx"));
    els.deliveryWordSecondaryButton.addEventListener("click", () => exportProjectAsset("docx"));
    els.deliveryBatchButton.addEventListener("click", openBatchModal);
    els.deliveryPrintButton.addEventListener("click", () => window.print());
    els.deliveryVariantsButton.addEventListener("click", () => openSuiteView("projects", { focusId: "variantStudio", openDetails: true }));

    [els.academicCitationStyle, els.academicImportFormat, els.academicImportContent, els.academicEvidenceRecord,
      els.academicEvidenceQuery, els.academicEvidenceText, els.academicClaims,
      els.academicReviewerComments, els.academicManuscriptChanges]
      .forEach((control) => {
        control.addEventListener("input", handlePhase2Input);
        control.addEventListener("change", handlePhase2Input);
      });
    els.academicTaskType.addEventListener("change", () => reconcileTaskContext("academic_task"));
    els.academicTitle.addEventListener("input", handleAcademicTaskTextInput);
    els.academicTitle.addEventListener("change", handleAcademicTaskTextInput);
    els.academicGoal.addEventListener("input", handleAcademicTaskTextInput);
    els.academicGoal.addEventListener("change", handleAcademicTaskTextInput);
    els.academicImportButton.addEventListener("click", importAcademicRecords);
    els.academicMatrixButton.addEventListener("click", generateAcademicMatrix);
    els.academicExtractEvidenceButton.addEventListener("click", extractAcademicEvidence);
    els.academicVerifyClaimsButton.addEventListener("click", verifyAcademicClaims);
    els.academicFormatCitationsButton.addEventListener("click", formatAcademicCitations);
    els.academicOutlineButton.addEventListener("click", generateAcademicOutline);
    els.academicRebuttalButton.addEventListener("click", generateAcademicRebuttal);

    els.projectSelect.addEventListener("change", () => selectProject(els.projectSelect.value));
    els.refreshProjectsButton.addEventListener("click", () => loadProjects(true));
    els.createProjectButton.addEventListener("click", openProjectModal);
    $$('[data-close-project]').forEach((button) => button.addEventListener("click", closeProjectModal));
    els.projectForm.addEventListener("submit", createProject);
    els.addProjectMaterialButton.addEventListener("click", addProjectMaterial);
    els.localDraftMode.addEventListener("change", () => {
      phase2State.local_draft_mode = els.localDraftMode.checked;
      persistPhase2State();
      setV2ServiceState(v2ServiceState === "connected" ? "connected" : "local");
      toast(els.localDraftMode.checked ? "本地预览模式已开启" : "本地预览模式已关闭，服务错误将直接提示", "info");
    });

    els.openSettingsDrawerButton.addEventListener("click", openSettings);
    els.settingsEngineButton.addEventListener("click", openSettings);
    els.probeV2Button.addEventListener("click", () => probeV2Capabilities(true));
    els.clearPhase2DraftsButton.addEventListener("click", clearPhase2Drafts);
    els.clearAllLocalDataButton.addEventListener("click", clearAllLocalData);

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
    window.addEventListener("beforeunload", persistPhase2State);
  }

  function restorePhase2State() {
    try {
      const saved = JSON.parse(localStorage.getItem(PHASE2_KEY) || "null");
      if (!saved || typeof saved !== "object") return;
      const defaults = freshPhase2State();
      phase2State = {
        ...defaults,
        ...saved,
        brief: { ...defaults.brief, ...(saved.brief || {}) },
        expression: { ...defaults.expression, ...(saved.expression || {}) },
        academic: { ...defaults.academic, ...(saved.academic || {}) },
      };
      phase2State.expression.results = Array.isArray(saved.expression?.results) ? saved.expression.results.map(String).slice(0, 12) : [];
      phase2State.projects = Array.isArray(saved.projects) ? saved.projects.filter((item) => item && typeof item === "object").slice(0, 100) : [];
      phase2State.project_drafts = saved.project_drafts && typeof saved.project_drafts === "object"
        ? Object.fromEntries(Object.entries(saved.project_drafts).filter(([, draft]) => draft && typeof draft === "object").slice(0, 5)) : {};
      phase2State.material_ids = Array.isArray(saved.material_ids) ? saved.material_ids.map(String).filter(Boolean).slice(0, 128) : [];
      phase2State.variants = Array.isArray(saved.variants) ? saved.variants.slice(0, 12) : [];
      phase2State.academic.records = Array.isArray(saved.academic?.records) ? saved.academic.records.slice(0, MAX_ACADEMIC_RECORDS) : [];
      phase2State.academic.matrix = Array.isArray(saved.academic?.matrix) ? saved.academic.matrix.slice(0, MAX_ACADEMIC_RECORDS) : [];
      phase2State.academic.evidence = Array.isArray(saved.academic?.evidence) ? saved.academic.evidence.slice(0, MAX_ACADEMIC_EVIDENCE) : [];
      phase2State.academic.claims = Array.isArray(saved.academic?.claims) ? saved.academic.claims.slice(0, 500) : [];
      phase2State.academic.recovered_claims = Array.isArray(saved.academic?.recovered_claims) ? saved.academic.recovered_claims.slice(0, 500) : [];
      phase2State.academic.recovered_claim_links = Array.isArray(saved.academic?.recovered_claim_links) ? saved.academic.recovered_claim_links.slice(0, 500) : [];
      phase2State.academic.claim_links = Array.isArray(saved.academic?.claim_links) ? saved.academic.claim_links.slice(0, 500) : [];
      phase2State.academic.claim_comments = Array.isArray(saved.academic?.claim_comments) ? saved.academic.claim_comments.slice(0, 500) : [];
      phase2State.academic.citations = Array.isArray(saved.academic?.citations) ? saved.academic.citations.slice(0, MAX_ACADEMIC_RECORDS) : [];
      phase2State.academic.rebuttal = Array.isArray(saved.academic?.rebuttal) ? saved.academic.rebuttal.slice(0, 100) : [];
      const focusAliases = { headline: "title", "lead-sentence": "topic_sentence", abstract: "opening", "key-sentence": "topic_sentence" };
      phase2State.expression.focus = focusAliases[phase2State.expression.focus] || phase2State.expression.focus || "title";
      const channelAliases = { internal: "document", website: "web", journal: "academic", multi: "document" };
      phase2State.brief.channel = channelAliases[phase2State.brief.channel] || phase2State.brief.channel || "document";
      if (!RECIPE_CATALOG[phase2State.brief.scenario_pack_id]) phase2State.brief.scenario_pack_id = "gongwen";
      if (!validRecipeId(phase2State.brief.scenario_pack_id, phase2State.brief.recipe_id)) phase2State.brief.recipe_id = RECIPE_CATALOG[phase2State.brief.scenario_pack_id][0][0];
    } catch (_) {
      phase2State = freshPhase2State();
    }
  }

  function persistPhase2State() {
    syncPhase2StateFromUI();
    captureCurrentProjectDraft();
    try { localStorage.setItem(PHASE2_KEY, JSON.stringify(phase2State)); }
    catch (_) { /* The main document save status already reports storage pressure. */ }
  }

  function schedulePhase2Save() {
    clearTimeout(phase2SaveTimer);
    phase2SaveTimer = window.setTimeout(persistPhase2State, 320);
  }

  function handlePhase2Input(event = null) {
    const briefControls = new Set([
      els.briefChannel, els.briefDeadline, els.briefLanguage, els.briefKeywords, els.briefConstraints,
    ]);
    const previousBrief = JSON.stringify(phase2State.brief);
    syncPhase2StateFromUI({ invalidate: false });
    if (briefControls.has(event?.target) && previousBrief !== JSON.stringify(phase2State.brief)) {
      clearTaskDerivedOutputs(activeRecipeContext());
    }
    const bindingInvalidated = invalidateSavedBriefBinding();
    if (bindingInvalidated) {
      renderVariants();
      updateProjectWorkflowStatus();
      renderDocumentContextStatus();
    }
    updateAcademicPrimaryAction();
    renderAcademicClaimLinks();
    renderAcademicCitations();
    renderAcademicOutline();
    renderAcademicRebuttal();
    renderAcademicIntegrity();
    updatePhase2Summaries();
    schedulePhase2Save();
  }

  function syncPhase2StateFromUI({ invalidate = true } = {}) {
    if (!els.briefContentType) return;
    const previousBrief = phase2State.brief;
    const nextBriefKeywords = els.briefKeywords.value.trim();
    const nextBriefConstraints = els.briefConstraints.value.trim();
    const briefKeywordsChanged = nextBriefKeywords !== previousBrief.keywords;
    const briefConstraintsChanged = nextBriefConstraints !== previousBrief.constraints;
    phase2State.brief = {
      ...previousBrief,
      content_type: els.briefContentType.value,
      channel: els.briefChannel.value,
      scenario_pack_id: els.briefScenarioPack.value,
      recipe_id: els.briefRecipe.value,
      deadline: els.briefDeadline.value,
      target_language: els.briefLanguage.value,
      keywords: nextBriefKeywords,
      constraints: nextBriefConstraints,
    };
    phase2State.expression = {
      ...phase2State.expression,
      focus: $("[data-expression-focus].is-active")?.dataset.expressionFocus || "title",
      instruction: els.expressionInstruction.value.trim(),
      count: Math.max(1, Math.min(12, Number(els.expressionCount.value) || 5)),
    };
    const academic = phase2State.academic;
    const claimsText = els.academicClaims.value;
    const claimsChanged = claimsText !== academic.claims_text;
    const citationStyleChanged = els.academicCitationStyle.value !== academic.citation_style;
    const writingTaskChanged = els.academicTaskType.value !== academic.task_type
      || els.academicTitle.value.trim() !== academic.title || els.academicGoal.value.trim() !== academic.goal;
    const rebuttalInputChanged = els.academicReviewerComments.value !== academic.reviewer_comments
      || els.academicManuscriptChanges.value !== academic.manuscript_changes;
    const outlineInputsChanged = writingTaskChanged || briefKeywordsChanged || briefConstraintsChanged;
    const integrityInputsChanged = claimsChanged || writingTaskChanged || citationStyleChanged || briefConstraintsChanged;
    phase2State.academic = {
      ...academic,
      task_type: els.academicTaskType.value,
      title: els.academicTitle.value.trim(),
      goal: els.academicGoal.value.trim(),
      citation_style: els.academicCitationStyle.value,
      import_format: els.academicImportFormat.value,
      import_content: els.academicImportContent.value,
      evidence_record_id: els.academicEvidenceRecord.value,
      evidence_query: els.academicEvidenceQuery.value.trim(),
      evidence_text: els.academicEvidenceText.value,
      claims_text: claimsText,
      claims: claimsChanged ? [] : academic.claims || [],
      claims_dirty: claimsChanged ? true : Boolean(academic.claims_dirty),
      claim_links: claimsChanged ? [] : academic.claim_links || [],
      claim_comments: claimsChanged ? [] : academic.claim_comments || [],
      coverage: claimsChanged ? null : academic.coverage,
      citations: citationStyleChanged ? [] : academic.citations || [],
      outline: outlineInputsChanged ? null : academic.outline,
      integrity: integrityInputsChanged ? null : academic.integrity,
      reviewer_comments: els.academicReviewerComments.value,
      manuscript_changes: els.academicManuscriptChanges.value,
      rebuttal: rebuttalInputChanged ? [] : academic.rebuttal || [],
    };
    if (invalidate) invalidateSavedBriefBinding();
  }

  function taskContextInput() {
    return {
      contentType: els.briefContentType.value,
      channel: els.briefChannel.value,
      packId: els.briefScenarioPack.value,
      recipeId: els.briefRecipe.value,
      documentType: els.documentType.value,
      academicTaskType: els.academicTaskType.value,
    };
  }

  function taskContextSignature(context = null) {
    const value = context || {
      scenarioPackId: phase2State.brief.scenario_pack_id,
      recipeId: phase2State.brief.recipe_id,
      contentType: phase2State.brief.content_type,
      channel: phase2State.brief.channel,
      documentType: appState.form.document_type,
      academicTaskType: phase2State.academic.task_type,
    };
    const packId = value.scenarioPackId;
    return JSON.stringify([
      packId, value.recipeId, value.contentType, value.channel,
      value.documentType, packId === "academic" ? value.academicTaskType : "",
    ]);
  }

  function ensureDocumentTypeOption(documentType) {
    const value = String(documentType || "").trim();
    if (!value) return;
    if (![...els.documentType.options].some((option) => option.value === value)) {
      els.documentType.append(makeOption(value, value));
    }
  }

  function activeRecipeContext() {
    if (phase2State.standalone_document) {
      return workspaceContext.resolveStandaloneDocumentContext(taskContextInput());
    }
    return workspaceContext.resolveWorkspaceContext(taskContextInput(), "restore");
  }

  function applyResolvedTaskContext(context) {
    phase2State.brief.content_type = context.contentType;
    phase2State.brief.channel = context.channel;
    phase2State.brief.scenario_pack_id = context.scenarioPackId;
    phase2State.brief.recipe_id = context.recipeId;
    phase2State.brief.recipe_content_type = context.documentType;
    const contentLabels = { "official-document": "规范公文", "leadership-speech": "领导讲话", "research-report": "调研报告", "news-release": "新闻通稿", "academic-paper": "学术论文", "general-writing": context.scenarioPackId === "workplace" ? "职场文字" : "传播内容" };
    const contentTypes = workspaceContext.PACK_CONTENT_TYPES[context.scenarioPackId];
    els.briefContentType.replaceChildren(...contentTypes.map((type) => makeOption(type, contentLabels[type])));
    els.briefContentType.disabled = contentTypes.length === 1;
    els.briefContentType.value = context.contentType;
    els.briefScenarioPack.value = context.scenarioPackId;
    updateRecipeOptions(context.recipeId, false);
    updateRecipeChannelOptions(context.channel, false);
    ensureDocumentTypeOption(context.documentType);
    els.documentType.value = context.documentType;
    appState.form.document_type = context.documentType;
    els.documentBadge.textContent = context.documentType;
    els.paperType.textContent = context.documentType;
    applyScenarioProfile(context);
    if (context.scenarioPackId === "academic") {
      const taskType = context.academicTaskType || "literature-review";
      setSelectValue(els.academicTaskType, taskType, "literature-review");
      phase2State.academic.task_type = taskType;
      els.academicTitle.value = els.topic.value.trim();
      els.academicGoal.value = els.purpose.value.trim();
      phase2State.academic.title = els.academicTitle.value;
      phase2State.academic.goal = els.academicGoal.value;
    }
    syncFormState();
  }

  function selectPendingRecipeMethodology(context) {
    const method = context?.methodology;
    if (!method?.id || !els.contentMethodology) return;
    if (![...els.contentMethodology.options].some((option) => option.value === method.id)) {
      els.contentMethodology.append(makeOption(method.id, method.name || method.id));
    }
    els.contentMethodology.value = method.id;
    appState.form.content_methodology_id = method.id;
    appState.form.custom_methodology = null;
    appState.form.title_formula_ids = [];
  }

  function recipeOutline(context) {
    return [...context.headings].map((heading) => ({ heading: String(heading), content: "" }));
  }

  function clearTaskDerivedOutputs(context = activeRecipeContext(), { discardDraft = false } = {}) {
    const hasRetainedDraft = !discardDraft && Boolean(els.documentTitle.value.trim() || documentPlainText());
    appState.document.candidates = [];
    appState.document.title_execution = null;
    appState.document.outline = recipeOutline(context);
    appState.review = null;
    appState.factAudit = null;
    appState.serverDocumentId = "";
    appState.serverDocumentVersion = 0;
    appState.checklist = [false, false, false, false, false, false];
    $$('.checklist input').forEach((checkbox) => { checkbox.checked = false; });
    els.checkProgress.textContent = "0/6";
    phase2State.expression.results = [];
    phase2State.selected_title = "";
    phase2State.master_asset_id = "";
    phase2State.master_asset_revision = null;
    phase2State.output_binding_hash = "";
    phase2State.document_stale = hasRetainedDraft;
    phase2State.workflow_id = "";
    phase2State.workflow_status = "";
    phase2State.variants = [];
    phase2State.academic.outline = null;
    phase2State.academic.integrity = null;
    if (!hasRetainedDraft) {
      appState.document.title = "";
      appState.document.html = "";
      appState.document.execution = null;
      els.documentTitle.value = "";
      els.documentEditor.replaceChildren();
      els.generationHero.classList.remove("is-hidden");
      els.documentWorkspace.classList.add("is-hidden");
    }
    renderCandidates();
    renderOutline();
    renderExpressionResults();
    renderVariants();
    resetReviewView();
    renderAcademicOutline();
    renderAcademicIntegrity();
    updateProjectWorkflowStatus();
    renderDocumentContextStatus();
  }

  function invalidateMethodologyCatalogRequest() {
    catalogRequestSerial += 1;
    methodologyCatalogReady = false;
  }

  function reconcileTaskContext(source, { invalidate = true, persist = true, reloadMethodology = true } = {}) {
    const previous = taskContextSignature();
    const context = phase2State.standalone_document && source === "restore"
      ? workspaceContext.resolveStandaloneDocumentContext(taskContextInput())
      : workspaceContext.resolveWorkspaceContext(taskContextInput(), source);
    const changed = previous !== taskContextSignature(context);
    if (changed && reloadMethodology) invalidateMethodologyCatalogRequest();
    if (changed) selectPendingRecipeMethodology(context);
    applyResolvedTaskContext(context);
    if (changed && invalidate) clearTaskDerivedOutputs(context);
    else if (!documentPlainText() && !appState.document.title) {
      appState.document.outline = recipeOutline(context);
      renderOutline();
    }
    syncPhase2StateFromUI({ invalidate: false });
    invalidateSavedBriefBinding();
    updateAcademicPrimaryAction();
    updatePhase2Summaries();
    updateCounts();
    if (reloadMethodology) void loadMethodologyCatalog(true);
    if (persist) {
      scheduleSave();
      schedulePhase2Save();
    }
    return context;
  }

  function handleAcademicTaskTextInput() {
    const title = els.academicTitle.value;
    const goal = els.academicGoal.value;
    const changed = title !== els.topic.value || goal !== els.purpose.value;
    els.topic.value = title;
    els.purpose.value = goal;
    handleFormInput({ target: changed ? els.topic : els.academicTitle });
  }

  function handleMethodologyChange() {
    const previous = JSON.stringify([
      appState.form.content_methodology_id,
      appState.form.custom_methodology,
    ]);
    updateMethodologyView({ persist: false });
    syncFormState();
    const next = JSON.stringify([
      appState.form.content_methodology_id,
      appState.form.custom_methodology,
    ]);
    if (previous !== next) clearTaskDerivedOutputs(activeRecipeContext());
    invalidateSavedBriefBinding();
    updatePhase2Summaries();
    scheduleSave();
    schedulePhase2Save();
  }

  function applyPhase2StateToUI() {
    const brief = phase2State.brief;
    if (!phase2State.project_id && (appState.serverDocumentId || appState.document.title || appState.document.html)) {
      phase2State.standalone_document = true;
    }
    setSelectValue(els.briefContentType, brief.content_type, "official-document");
    setSelectValue(els.briefChannel, brief.channel, "document");
    setSelectValue(els.briefScenarioPack, brief.scenario_pack_id, "gongwen");
    updateRecipeOptions(brief.recipe_id, false);
    els.briefDeadline.value = String(brief.deadline || "");
    setSelectValue(els.briefLanguage, brief.target_language, "zh-CN");
    els.briefKeywords.value = String(brief.keywords || "");
    els.briefConstraints.value = String(brief.constraints || "");
    els.briefStatus.textContent = brief.saved_at ? `已整理 · ${formatDateTime(brief.saved_at)}` : "仅在主动提交时调用服务";
    els.localDraftMode.checked = phase2State.local_draft_mode !== false;
    renderProjectOptions();
    updateProjectWorkflowStatus();

    selectExpressionFocus(phase2State.expression.focus || "title", false);
    els.expressionInstruction.value = String(phase2State.expression.instruction || "");
    setSelectValue(els.expressionCount, String(phase2State.expression.count || 5), "5");

    const academic = phase2State.academic;
    setSelectValue(els.academicTaskType, academic.task_type, "literature-review");
    els.academicTitle.value = String(academic.title || "");
    els.academicGoal.value = String(academic.goal || "");
    setSelectValue(els.academicCitationStyle, academic.citation_style, "gb-t-7714");
    setSelectValue(els.academicImportFormat, academic.import_format, "bibtex");
    els.academicImportContent.value = String(academic.import_content || "");
    els.academicEvidenceQuery.value = String(academic.evidence_query || "");
    els.academicEvidenceText.value = String(academic.evidence_text || "");
    els.academicClaims.value = String(academic.claims_text || "");
    els.academicReviewerComments.value = String(academic.reviewer_comments || "");
    els.academicManuscriptChanges.value = String(academic.manuscript_changes || "");

    reconcileTaskContext("restore", { persist: false, reloadMethodology: false });
    if (phase2State.project_id && (phase2State.master_asset_id || documentPlainText()) && !phase2State.output_binding_hash) {
      phase2State.document_stale = true;
    }

    renderExpressionResults();
    renderVariants();
    renderAcademicRecords();
    renderAcademicMatrix();
    renderAcademicEvidence();
    renderAcademicClaimLinks();
    renderAcademicCitations();
    renderAcademicOutline();
    renderAcademicRebuttal();
    renderAcademicIntegrity();
    renderDocumentContextStatus();
    updateAcademicPrimaryAction();
    updatePhase2Summaries();
    openSuiteView(phase2State.view || "home", { persist: false });
  }

  function setSelectValue(select, value, fallback) {
    const candidate = String(value || "");
    select.value = [...select.options].some((option) => option.value === candidate) ? candidate : fallback;
  }

  function validRecipeId(packId, recipeId) {
    return (RECIPE_CATALOG[packId] || []).some(([id]) => id === recipeId);
  }

  function updateRecipeOptions(preferred = "", persist = true) {
    const packId = els.briefScenarioPack.value || "gongwen";
    const recipes = RECIPE_CATALOG[packId] || RECIPE_CATALOG.gongwen;
    const requested = String(preferred || phase2State.brief.recipe_id || "");
    const selected = recipes.some(([id]) => id === requested) ? requested : recipes[0][0];
    els.briefRecipe.replaceChildren(...recipes.map(([id, name]) => makeOption(id, name)));
    els.briefRecipe.value = selected;
    phase2State.brief.scenario_pack_id = packId;
    phase2State.brief.recipe_id = selected;
    const contentType = recipes.find(([id]) => id === selected)?.[2];
    if (contentType) phase2State.brief.recipe_content_type = contentType;
    updateRecipeChannelOptions(phase2State.brief.channel, false);
    if (persist) {
      updatePhase2Summaries();
      schedulePhase2Save();
    }
  }

  function updateRecipeChannelOptions(preferred = "", persist = true) {
    const packId = els.briefScenarioPack.value || "gongwen";
    const recipeId = els.briefRecipe.value || RECIPE_CATALOG[packId]?.[0]?.[0];
    const channels = (RECIPE_CATALOG[packId] || []).find(([id]) => id === recipeId)?.[3] || ["document"];
    const labels = { document: packId === "gongwen" ? "机关文件" : "文档 / 报告", email: "电子邮件", meeting: "会议沟通", presentation: "演示汇报", web: "网站 / 公众号", social: "社交媒体", academic: "学术期刊" };
    const selected = channels.includes(String(preferred || phase2State.brief.channel)) ? String(preferred || phase2State.brief.channel) : channels[0];
    els.briefChannel.replaceChildren(...channels.map((channel) => makeOption(channel, labels[channel] || channel)));
    els.briefChannel.value = selected;
    phase2State.brief.channel = selected;
    if (persist) {
      updatePhase2Summaries();
      schedulePhase2Save();
    }
  }

  function openSuiteView(view, options = {}) {
    const validViews = new Set(["home", "projects", "knowledge", "recipes", "review", "delivery", "academic", "settings"]);
    const nextView = validViews.has(view) ? view : "home";
    $$("[data-suite-page]").forEach((page) => {
      const active = page.dataset.suitePage === nextView;
      page.hidden = !active;
      page.classList.toggle("is-active", active);
    });
    $$("[data-suite-view]").forEach((button) => {
      const active = button.dataset.suiteView === nextView;
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    if (nextView !== "projects") document.body.classList.remove("focus-mode");
    phase2State.view = nextView;
    if (options.persist !== false) schedulePhase2Save();
    updatePhase2Summaries();
    if (nextView === "knowledge") void refreshKnowledgeStats();
    if (nextView === "recipes") void loadWorkflowDefinitions(false);
    if (options.focusId) {
      window.requestAnimationFrame(() => focusProjectControl(options.focusId, options.openDetails));
    }
  }

  function focusProjectControl(id, forceDetails = false) {
    const target = document.getElementById(id);
    if (!target) return;
    const details = target.matches("details") ? target : target.closest("details");
    if (details) details.open = true;
    const panel = target.matches(".mobile-panel") ? target : target.closest(".mobile-panel");
    if (panel && window.matchMedia("(max-width: 1080px)").matches) {
      $$(".mobile-panel").forEach((item) => item.classList.toggle("is-active", item === panel));
      $$(".mobile-tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.mobilePanel === panel.id));
    }
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    if (typeof target.focus === "function" && !target.matches("section, details, aside")) {
      window.setTimeout(() => target.focus({ preventScroll: true }), 180);
    }
  }

  function currentBriefPayload() {
    const packId = phase2State.brief.scenario_pack_id || "gongwen";
    const recipeId = validRecipeId(packId, phase2State.brief.recipe_id) ? phase2State.brief.recipe_id : RECIPE_CATALOG[packId][0][0];
    const recipe = RECIPE_CATALOG[packId].find(([id]) => id === recipeId) || RECIPE_CATALOG[packId][0];
    return {
      title: els.topic.value.trim() || "未命名写作任务",
      goal: els.purpose.value.trim(),
      audience: els.audience.value.trim(),
      channel: phase2State.brief.channel,
      content_type: phase2State.brief.content_type,
      service_content_type: recipe[2],
      scenario_pack_id: packId,
      recipe_id: recipeId,
      tone: $('input[name="tone"]:checked')?.value || "严谨规范",
      length: els.length.value,
      target_language: phase2State.brief.target_language,
      constraints: boundedTextList([`表达方法：${els.referenceStyle.value}。${selectedStyleDescription()}`, els.requirements.value, phase2State.brief.constraints], 500, 32),
      keywords: [...new Set(phase2State.brief.keywords.split(/[，,、;；\s]+/).map((item) => item.trim()).filter(Boolean))].slice(0, 32),
      knowledge_item_ids: phase2State.material_ids.slice(0, 128),
      model_profile_id: null,
      deadline: phase2State.brief.deadline || null,
      document_type: els.documentType.value,
    };
  }

  function boundedTextList(values, maxLength, maxItems) {
    const output = [];
    values.flatMap((value) => String(value || "").split(/\r?\n+|[；;]+/)).map((value) => value.trim()).filter(Boolean).forEach((value) => {
      for (let offset = 0; offset < value.length && output.length < maxItems; offset += maxLength) output.push(value.slice(offset, offset + maxLength));
    });
    return [...new Set(output)].slice(0, maxItems);
  }

  function serverStructureOverride() {
    const recipeMethodology = activeRecipeContext().methodology;
    const selectedId = methodologyCatalogReady
      ? (els.contentMethodology?.value || "")
      : String(appState.form.content_methodology_id || "");
    if (!selectedId || selectedId === recipeMethodology.id) return [];
    let selected;
    if (selectedId === "custom") {
      const custom = methodologyCatalogReady ? customMethodologyPayload() : appState.form.custom_methodology;
      const steps = Array.isArray(custom?.steps) ? custom.steps : [];
      selected = {
        id: "custom",
        headings: steps,
        section_purposes: steps.map((step) => `按“${step}”步骤组织本节内容。`),
      };
    } else {
      selected = methodologyCatalog.contentMethodologies.find((item) => item.id === selectedId)
        || recipeMethodology;
    }
    const headings = Array.isArray(selected?.headings) ? selected.headings : [];
    const purposes = Array.isArray(selected?.section_purposes) ? selected.section_purposes : [];
    const idBase = String(selected?.id || "section").replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "section";
    return headings.slice(0, 24).map((heading, index) => ({
      id: `${idBase}-${index + 1}`.slice(0, 80),
      title: String(heading || "").trim(),
      purpose: String(purposes[index] || `围绕“${heading}”展开。`).trim(),
      required: true,
    })).filter((section) => section.title && section.purpose);
  }

  function serverBriefPayload() {
    const brief = currentBriefPayload();
    return {
      title: brief.title,
      goal: brief.goal,
      audience: brief.audience,
      channel: brief.channel,
      content_type: brief.service_content_type,
      scenario_pack_id: brief.scenario_pack_id,
      recipe_id: brief.recipe_id,
      tone: brief.tone,
      length: brief.length,
      target_language: brief.target_language,
      constraints: brief.constraints,
      keywords: brief.keywords,
      material_ids: serverMaterialIds(),
      model_profile_id: brief.model_profile_id,
      selected_title: phase2State.selected_title || undefined,
      structure_override: serverStructureOverride(),
    };
  }

  function serverMaterialIds() {
    return phase2State.material_ids.filter((id) => !String(id).startsWith("local-material-")).slice(0, 128);
  }

  function serverGenerationBriefPayload() {
    const { title, ...rest } = serverBriefPayload();
    return { topic: title, ...rest };
  }

  function currentBriefBindingHash(payload = serverBriefPayload()) {
    const methodologyId = String(appState.form.content_methodology_id || "");
    const methodologyOverride = appState.form.custom_methodology || null;
    const titleFormulaIds = Array.isArray(appState.form.title_formula_ids) ? appState.form.title_formula_ids : [];
    const titleFormulaOverride = appState.form.custom_title_formula || null;
    return simpleHash(workspaceContext.briefBindingSignature({
      payload,
      contentTypeFamily: phase2State.brief.content_type,
      deadline: phase2State.brief.deadline,
      documentType: appState.form.document_type,
      referenceStyle: appState.form.reference_style,
      contentMethodologyId: methodologyId,
      customMethodology: methodologyOverride,
      selectedTitle: phase2State.selected_title || "",
      titleFormulaIds,
      customTitleFormula: titleFormulaOverride,
      factLock: Boolean(appState.form.factLock),
      materialsHash: simpleHash(currentFactualMaterialText()),
      styleReferences: appState.styleReferences || [],
      workspaceMaterialIds: phase2State.material_ids,
    }));
  }

  function invalidateSavedBriefBinding() {
    const bindingHash = currentBriefBindingHash();
    const savedHash = String(phase2State.brief.payload_hash || "");
    const outputHash = String(phase2State.output_binding_hash || "");
    const briefChanged = Boolean(phase2State.brief.id) && (!savedHash || savedHash !== bindingHash);
    const outputChanged = Boolean(outputHash) && outputHash !== bindingHash;
    if (!briefChanged && !outputChanged) return false;
    if (briefChanged) {
      phase2State.brief.id = "";
      phase2State.brief.saved_at = "";
      phase2State.brief.payload_hash = "";
    }
    if (outputChanged) {
      phase2State.master_asset_id = "";
      phase2State.master_asset_revision = null;
      phase2State.output_binding_hash = "";
      phase2State.workflow_id = "";
      phase2State.workflow_status = "";
      phase2State.variants = [];
      appState.review = null;
      appState.factAudit = null;
      phase2State.academic.integrity = null;
      phase2State.document_stale = Boolean(els.documentTitle.value.trim() || documentPlainText());
    }
    return true;
  }

  function validateServerBrief() {
    if (!els.topic.value.trim()) { openSuiteView("projects"); els.topic.focus(); throw new Error("请先填写写作主题"); }
    if (!els.purpose.value.trim()) { openSuiteView("projects"); els.purpose.focus(); throw new Error("请先填写写作目的"); }
    if (!els.audience.value.trim()) { openSuiteView("projects"); els.audience.focus(); throw new Error("请先填写阅读对象"); }
    return serverBriefPayload();
  }

  async function normalizeBrief() {
    const projectId = requireActiveProject("保存任务简报");
    if (!projectId) return;
    const operationSerial = projectSwitchSerial;
    setButtonBusy(els.normalizeBriefButton, true, "正在整理…");
    els.briefStatus.textContent = "正在统一任务要素…";
    try {
      const prepared = await prepareServerBrief(projectId, operationSerial);
      if (!prepared) return null;
      return await persistPreparedBrief(projectId, operationSerial, prepared, { announce: true });
    } catch (error) {
      if (projectOperationIsStale(projectId, operationSerial, error)) return null;
      els.briefStatus.textContent = "请检查任务要素后重试";
      toast(readError(error, "任务简报整理未完成"), "error");
      return null;
    } finally {
      if (!projectOperationIsStale(projectId, operationSerial)) setButtonBusy(els.normalizeBriefButton, false);
    }
  }

  async function progressiveV2(path, options = {}, localFallback) {
    try {
      const data = await apiRequest(path, options);
      setV2ServiceState("connected");
      return { data, source: "server" };
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      const status = Number(error?.status || 0);
      const canUseLocal = options.body?.live !== true && phase2State.local_draft_mode !== false && (!status || [404, 405, 500, 501, 502, 503, 504].includes(status));
      if (!canUseLocal || typeof localFallback !== "function") throw error;
      setV2ServiceState("local");
      return { data: await localFallback(error), source: "local", error };
    }
  }

  async function progressiveAcademicV2(path, options, localFallback, includeEvidence = true) {
    const hasLocalRecords = phase2State.academic.records.some((record) => record?._server_synced === false);
    const hasLocalEvidence = includeEvidence && phase2State.academic.evidence.some((snippet) => snippet?._server_synced === false);
    if ((hasLocalRecords || hasLocalEvidence) && phase2State.local_draft_mode !== false && typeof localFallback === "function") {
      return { data: await localFallback(), source: "local", error: new Error("当前学术资料包含尚未写入服务端的本地记录") };
    }
    return progressiveV2(path, options, localFallback);
  }

  async function initializePhase2Service() {
    const connected = await probeV2Capabilities();
    await loadWorkflowDefinitions(false);
    if (connected) await loadProjects(false);
    else renderProjectOptions();
  }

  async function probeV2Capabilities(notify = false) {
    if (accessTokenRequired && !sessionAccessToken) {
      setV2ServiceState("waiting");
      return false;
    }
    setV2ServiceState("checking");
    if (notify) setButtonBusy(els.probeV2Button, true, "正在检测…");
    try {
      await apiRequest("/api/v2/bootstrap");
      setV2ServiceState("connected");
      if (notify) toast("第二阶段项目服务已连接", "success");
      return true;
    } catch (_) {
      setV2ServiceState("local");
      if (notify) toast("当前使用本地预览能力，现有公文流程保持可用", "info");
      return false;
    } finally {
      if (notify) setButtonBusy(els.probeV2Button, false);
    }
  }

  function isLocalProject(projectId = phase2State.project_id) {
    return String(projectId || "").startsWith("local-project-") || phase2State.project_source === "local";
  }

  function requireActiveProject(action) {
    const projectId = String(phase2State.project_id || "").trim();
    if (projectAssetsLoading) {
      els.projectContextStatus.textContent = "正在同步项目资产";
      toast("项目资产仍在同步，请稍候再继续", "warning");
      return "";
    }
    if (projectId) return projectId;
    els.projectContextStatus.textContent = `请先选择项目再${action}`;
    openProjectModal();
    toast(`请先选择或新建项目，再${action}`, "warning");
    return "";
  }

  function projectOperationIsStale(projectId, operationSerial, error = null) {
    return error?.name === "AbortError"
      || operationSerial !== projectSwitchSerial
      || String(phase2State.project_id || "") !== String(projectId || "");
  }

  function currentSourceInputHash() {
    return simpleHash(workspaceContext.generationInputSignature({
      projectId: String(phase2State.project_id || ""),
      briefBindingHash: currentBriefBindingHash(),
      document: {
        title: els.documentTitle.value.trim(),
        content_hash: simpleHash(documentPlainText()),
      },
      expression: {
        focus: phase2State.expression.focus,
        instruction: els.expressionInstruction.value.trim(),
        count: Number(els.expressionCount.value) || 0,
      },
      variant: {
        channels: $$('input[type="checkbox"]:checked', els.variantChannels).map((item) => item.value),
        length: els.variantLength.value,
        instruction: els.variantInstruction.value.trim(),
      },
      academic: {
        task_type: els.academicTaskType.value,
        title: els.academicTitle.value.trim(),
        goal: els.academicGoal.value.trim(),
        citation_style: els.academicCitationStyle.value,
        claims: els.academicClaims.value,
        reviewer_comments: els.academicReviewerComments.value,
        manuscript_changes: els.academicManuscriptChanges.value,
        records: phase2State.academic.records.map((item) => [item.id, item.source_hash]),
        evidence: phase2State.academic.evidence.map((item) => [item.id, item.content_hash]),
      },
      model: [settings.mode, settings.providerName, settings.baseUrl, settings.modelName, modelSettingsSerial],
    }));
  }

  function captureInputOperation(projectId = phase2State.project_id) {
    return {
      projectId: String(projectId || ""),
      projectSerial: projectSwitchSerial,
      inputHash: currentSourceInputHash(),
    };
  }

  function currentDocumentSaveOperation() {
    return {
      documentId: String(appState.serverDocumentId || ""),
      documentVersion: Number(appState.serverDocumentVersion || 0),
      editorHash: currentSourceInputHash(),
      projectId: String(phase2State.project_id || ""),
      projectSerial: projectSwitchSerial,
    };
  }

  function inputOperationIsStale(operation, error = null) {
    return error?.name === "AbortError" || !workspaceContext.operationMatches(operation, {
      projectId: String(phase2State.project_id || ""),
      projectSerial: projectSwitchSerial,
      inputHash: currentSourceInputHash(),
    });
  }

  function requireValidPage(response, label, expectedOffset, expectedTotal = null, expectedLimit = PAGE_SIZE) {
    if (!responseValidators?.validatePage?.(response, {
      expectedOffset,
      expectedLimit,
      expectedTotal,
    })) throw new Error(`${label}分页响应无效`);
    return response;
  }

  async function readAllPages(pathForPage, label) {
    const items = [];
    let offset = 0;
    let expectedTotal = null;
    for (let page = 0; page < MAX_PAGE_COUNT; page += 1) {
      const response = await apiRequest(pathForPage(offset, PAGE_SIZE));
      requireValidPage(response, label, offset, expectedTotal);
      if (expectedTotal === null) expectedTotal = response.total;
      items.push(...response.items);
      if (!response.has_more) return { items, total: response.total };
      if (!response.count) throw new Error(`${label}分页没有前进`);
      offset += response.count;
    }
    throw new Error(`${label}数据超过单次读取上限`);
  }

  function resetProjectActionButtons() {
    [
      "normalizeBriefButton", "addProjectMaterialButton", "runProjectWorkflowButton",
      "generateExpressionsButton", "generateVariantsButton", "searchKnowledgeButton",
      "hubRunReviewButton", "deliveryWordButton", "deliveryWordSecondaryButton",
      "academicImportButton", "academicMatrixButton", "academicExtractEvidenceButton",
      "academicVerifyClaimsButton", "academicFormatCitationsButton", "academicOutlineButton",
      "academicRebuttalButton",
    ].forEach((id) => { if (els[id]) setButtonBusy(els[id], false); });
  }

  function renderProjectOptions() {
    if (!els.projectSelect) return;
    const projects = Array.isArray(phase2State.projects) ? phase2State.projects : [];
    const options = [makeOption("", projects.length ? "选择项目" : "选择或新建项目")];
    projects.forEach((project) => {
      const option = makeOption(String(project.id || ""), String(project.name || "未命名项目"));
      if (project.source === "local") option.textContent += " · 本地预览";
      options.push(option);
    });
    if (phase2State.project_id && !projects.some((project) => String(project.id) === String(phase2State.project_id))) {
      options.push(makeOption(phase2State.project_id, phase2State.project_name || "当前项目"));
    }
    els.projectSelect.replaceChildren(...options);
    els.projectSelect.value = phase2State.project_id || "";
    els.projectContextStatus.textContent = phase2State.project_id
      ? (projectAssetsLoading ? "正在同步" : isLocalProject() ? "本地预览" : "服务端项目")
      : phase2State.standalone_document ? "独立文稿" : "尚未选择";
    els.projectContextStatus.classList.toggle("is-local", isLocalProject());
  }

  function captureCurrentProjectDraft() {
    const projectId = String(phase2State.project_id || "");
    if (!projectId || !els.documentEditor) return;
    const drafts = phase2State.project_drafts && typeof phase2State.project_drafts === "object" ? phase2State.project_drafts : {};
    drafts[projectId] = {
      updated_at: Date.now(),
      app_state: structuredCloneSafe(appState),
      brief: structuredCloneSafe(phase2State.brief),
      expression: structuredCloneSafe(phase2State.expression),
      selected_title: phase2State.selected_title,
      master_asset_id: phase2State.master_asset_id,
      master_asset_revision: phase2State.master_asset_revision,
      output_binding_hash: phase2State.output_binding_hash,
      document_stale: phase2State.document_stale,
      workflow_id: phase2State.workflow_id,
      workflow_status: phase2State.workflow_status,
      material_ids: [...phase2State.material_ids],
      variants: structuredCloneSafe(phase2State.variants),
      academic: structuredCloneSafe(phase2State.academic),
    };
    const retained = Object.entries(drafts).sort(([, left], [, right]) => Number(right?.updated_at || 0) - Number(left?.updated_at || 0)).slice(0, 5);
    phase2State.project_drafts = Object.fromEntries(retained);
  }

  function restoreProjectDraft(projectId) {
    const draft = phase2State.project_drafts?.[projectId];
    if (!draft || typeof draft !== "object" || !draft.app_state) return false;
    const defaults = freshState();
    appState = {
      ...defaults,
      ...structuredCloneSafe(draft.app_state),
      form: { ...defaults.form, ...(draft.app_state.form || {}) },
      document: { ...defaults.document, ...(draft.app_state.document || {}) },
      exportMeta: { ...defaults.exportMeta, ...(draft.app_state.exportMeta || {}) },
    };
    phase2State.brief = { ...freshPhase2State().brief, ...(draft.brief || {}) };
    phase2State.expression = { ...freshPhase2State().expression, ...(draft.expression || {}) };
    phase2State.selected_title = String(draft.selected_title || "");
    phase2State.master_asset_id = String(draft.master_asset_id || "");
    phase2State.master_asset_revision = Number(draft.master_asset_revision) || null;
    phase2State.output_binding_hash = String(draft.output_binding_hash || "");
    phase2State.document_stale = Boolean(draft.document_stale);
    phase2State.workflow_id = String(draft.workflow_id || "");
    phase2State.workflow_status = String(draft.workflow_status || "");
    phase2State.material_ids = Array.isArray(draft.material_ids) ? draft.material_ids.map(String).slice(0, 128) : [];
    phase2State.variants = Array.isArray(draft.variants) ? structuredCloneSafe(draft.variants) : [];
    phase2State.academic = { ...freshPhase2State().academic, ...(structuredCloneSafe(draft.academic) || {}) };
    applyStateToUI();
    applyPhase2StateToUI();
    return true;
  }

  async function readAcademicProjectCollection(projectId, resource, extraQuery = {}) {
    const result = await readAllPages((offset, limit) => {
      const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      Object.entries(extraQuery).forEach(([key, value]) => query.set(key, String(value)));
      return `/api/v2/projects/${encodeURIComponent(projectId)}/academic/${resource}?${query.toString()}`;
    }, `学术项目的 ${resource} `);
    return result.items;
  }

  async function hydrateAcademicProject(projectId, operationSerial) {
    const [records, evidence, matrices, claims, links] = await Promise.all([
      readAcademicProjectCollection(projectId, "literature", { include_abstract: true }),
      readAcademicProjectCollection(projectId, "evidence"),
      readAcademicProjectCollection(projectId, "matrices"),
      readAcademicProjectCollection(projectId, "claims"),
      readAcademicProjectCollection(projectId, "citation-links"),
    ]);
    if (projectOperationIsStale(projectId, operationSerial)) return false;
    const recordIds = new Set();
    records.forEach((record) => {
      const id = String(record?.id || "").trim();
      if (!id || !String(record?.title || "").trim() || recordIds.has(id)) throw new Error("学术项目包含无效或重复的参考文献记录");
      recordIds.add(id);
    });
    const evidenceIds = new Set();
    evidence.forEach((snippet) => {
      const id = String(snippet?.id || "").trim();
      if (!id || evidenceIds.has(id) || !recordIds.has(String(snippet?.record_id || "")) || !String(snippet?.text || "").trim()) throw new Error("学术项目包含无效的证据片段");
      evidenceIds.add(id);
    });
    const claimIds = new Set();
    claims.forEach((claim) => {
      const id = String(claim?.id || "").trim();
      if (!id || claimIds.has(id) || !String(claim?.text || "").trim()) throw new Error("学术项目包含无效的研究论断");
      claimIds.add(id);
    });
    links.forEach((link) => {
      if (!claimIds.has(String(link?.claim_id || ""))
        || !recordIds.has(String(link?.record_id || ""))
        || !evidenceIds.has(String(link?.evidence_id || ""))) throw new Error("学术项目包含无法追溯的引用链接");
    });
    if (matrices.some((matrix) => !matrix || typeof matrix !== "object" || !String(matrix.id || "").trim() || !Array.isArray(matrix.rows))) throw new Error("学术项目的文献矩阵响应无效");
    const latestMatrix = matrices[0] || null;
    const existingRecords = Array.isArray(phase2State.academic.records) ? phase2State.academic.records : [];
    const existingEvidence = Array.isArray(phase2State.academic.evidence) ? phase2State.academic.evidence : [];
    const mergedRecords = [...new Map([...existingRecords, ...records.map((record) => ({ ...record, _server_synced: true }))].map((record) => [String(record.id), record])).values()].slice(0, MAX_ACADEMIC_RECORDS);
    const visibleRecordIds = new Set(mergedRecords.map((record) => String(record.id)));
    const mergedEvidence = [...new Map([...existingEvidence, ...evidence.map((snippet) => ({ ...snippet, _server_synced: true }))].map((snippet) => [String(snippet.id), snippet])).values()]
      .filter((snippet) => visibleRecordIds.has(String(snippet.record_id))).slice(0, MAX_ACADEMIC_EVIDENCE);
    const hadLocalMatrix = Array.isArray(phase2State.academic.matrix) && phase2State.academic.matrix.length > 0;
    const localClaims = academicClaims();
    const adoptServerClaims = !localClaims.length && !phase2State.academic.claims_dirty;
    const activeClaims = adoptServerClaims ? claims.slice(0, 500) : localClaims;
    const activeLinks = Array.isArray(phase2State.academic.claim_links) ? phase2State.academic.claim_links : [];
    const activeComments = Array.isArray(phase2State.academic.claim_comments) ? phase2State.academic.claim_comments : [];
    phase2State.academic.records = mergedRecords;
    phase2State.academic.evidence = mergedEvidence;
    phase2State.academic.matrix = hadLocalMatrix ? phase2State.academic.matrix.slice(0, MAX_ACADEMIC_RECORDS) : (latestMatrix?.rows || []).filter((row) => visibleRecordIds.has(String(row?.record_id || ""))).slice(0, MAX_ACADEMIC_RECORDS);
    phase2State.academic.matrix_meta = hadLocalMatrix ? phase2State.academic.matrix_meta || null : latestMatrix ? {
      id: String(latestMatrix.id),
      query: String(latestMatrix.query || ""),
      themes: Array.isArray(latestMatrix.themes) ? latestMatrix.themes.map(String) : [],
    } : null;
    phase2State.academic.claims = activeClaims;
    phase2State.academic.recovered_claims = claims.slice(0, 500);
    phase2State.academic.recovered_claim_links = links.filter((link) => visibleRecordIds.has(String(link.record_id)) && mergedEvidence.some((snippet) => String(snippet.id) === String(link.evidence_id))).slice(0, 500);
    if (adoptServerClaims) {
      phase2State.academic.claims_text = activeClaims.map((claim) => String(claim.text)).join("\n");
      els.academicClaims.value = phase2State.academic.claims_text;
    }
    phase2State.academic.claim_links = validAcademicLinks(adoptServerClaims ? links : activeLinks, activeClaims);
    phase2State.academic.claim_comments = normalizeClaimComments(adoptServerClaims ? [] : activeComments, activeClaims, phase2State.academic.claim_links);
    const requiredClaims = activeClaims.filter((claim) => claim.requires_citation !== false);
    const supportedClaims = new Set(phase2State.academic.claim_links.filter((link) => link.status === "verified" && link.relation === "supports").map((link) => link.claim_id));
    phase2State.academic.coverage = requiredClaims.length ? requiredClaims.filter((claim) => supportedClaims.has(claim.id)).length / requiredClaims.length : null;
    phase2State.academic.restore_totals = { records: records.length, evidence: evidence.length, matrices: matrices.length, claims: claims.length, links: links.length };
    renderAcademicRecords();
    renderAcademicMatrix();
    renderAcademicEvidence();
    renderAcademicClaimLinks();
    renderAcademicIntegrity();
    persistPhase2State();
    return true;
  }

  async function restoreSelectedServerProject(projectId, operationSerial, notify = false, loadAsset = true) {
    projectAssetsLoading = true;
    renderProjectOptions();
    if (loadAsset) {
      const inputOperation = captureInputOperation(projectId);
      const expectedBriefId = String(phase2State.brief.id || "");
      await syncProjectAssets(notify, true, "", projectId, inputOperation, expectedBriefId, Boolean(expectedBriefId));
    }
    if (!projectOperationIsStale(projectId, operationSerial)) {
      try {
        await hydrateAcademicProject(projectId, operationSerial);
      } catch (error) {
        if (!projectOperationIsStale(projectId, operationSerial, error)) {
          toast(`学术项目恢复失败：${readError(error, "请检查服务")}`, "error");
        }
      }
    }
    if (operationSerial === projectSwitchSerial && String(phase2State.project_id || "") === String(projectId)) {
      projectAssetsLoading = false;
      renderProjectOptions();
      updateProjectWorkflowStatus();
    }
  }

  async function loadProjects(notify = false) {
    const requestSerial = ++projectListRequestSerial;
    const operationSerial = projectSwitchSerial;
    const selectedProjectId = String(phase2State.project_id || "");
    const responseIsStale = () => requestSerial !== projectListRequestSerial
      || operationSerial !== projectSwitchSerial
      || selectedProjectId !== String(phase2State.project_id || "");
    setButtonBusy(els.refreshProjectsButton, true, "…");
    try {
      let response = await apiRequest("/api/v2/projects?limit=100&offset=0");
      if (responseIsStale()) return;
      validateProjectPage(response, 0, null);
      const expectedTotal = response.total;
      const serverItems = [...response.items];
      let pageCount = 1;
      while (response.has_more === true && pageCount < MAX_PAGE_COUNT) {
        const nextOffset = response.offset + response.count;
        if (nextOffset <= response.offset) throw new Error("项目服务分页游标无效");
        response = await apiRequest(`/api/v2/projects?limit=100&offset=${nextOffset}`);
        if (responseIsStale()) return;
        validateProjectPage(response, nextOffset, expectedTotal);
        serverItems.push(...response.items);
        pageCount += 1;
      }
      if (response.has_more) throw new Error("项目数据超过单次恢复上限");
      const listingComplete = true;
      if (responseIsStale()) return;
      const validServerItems = serverItems.filter((project) => project && typeof project === "object" && String(project.id || "").trim());
      if (validServerItems.length !== serverItems.length || new Set(validServerItems.map((project) => String(project.id))).size !== validServerItems.length) throw new Error("项目服务返回了缺少或重复 ID 的项目");
      const localItems = (phase2State.projects || []).filter((project) => project.source === "local");
      const retainedCurrent = !listingComplete && phase2State.project_id
        ? (phase2State.projects || []).filter((project) => String(project.id) === String(phase2State.project_id))
        : [];
      const map = new Map([...localItems, ...retainedCurrent, ...validServerItems.map((project) => ({ ...project, source: "server" }))].map((project) => [String(project.id), project]));
      phase2State.projects = [...map.values()];
      if (listingComplete && phase2State.project_id && !map.has(String(phase2State.project_id))) await selectProject("");
      setV2ServiceState("connected");
      renderProjectOptions();
      persistPhase2State();
      const currentProjectId = String(phase2State.project_id || "");
      if (currentProjectId && !isLocalProject(currentProjectId)) {
        const academicResult = await Promise.allSettled([hydrateAcademicProject(currentProjectId, projectSwitchSerial)]);
        if (academicResult[0].status === "rejected" && notify) toast(`学术项目恢复失败：${readError(academicResult[0].reason, "请检查服务")}`, "error");
      }
      if (notify) toast(listingComplete ? `已读取 ${validServerItems.length} 个服务端项目` : `已读取前 ${validServerItems.length} 个服务端项目，当前选择已保留`, listingComplete ? "success" : "warning");
    } catch (error) {
      if (responseIsStale() || error?.name === "AbortError") return;
      setV2ServiceState("local");
      renderProjectOptions();
      if (notify) toast(`项目服务读取失败：${readError(error, "请检查服务状态")}`, "error");
    } finally {
      if (requestSerial === projectListRequestSerial) setButtonBusy(els.refreshProjectsButton, false);
    }
  }

  function validateProjectPage(response, expectedOffset, expectedTotal) {
    requireValidPage(response, "项目服务", expectedOffset, expectedTotal);
  }

  async function selectProject(projectId, { preserveWorkspace = false } = {}) {
    const nextId = String(projectId || "");
    if (nextId === phase2State.project_id) return;
    captureCurrentProjectDraft();
    const switchSerial = ++projectSwitchSerial;
    invalidateMethodologyCatalogRequest();
    projectRequestController.abort(new DOMException("项目已切换，上一项目请求已取消", "AbortError"));
    projectRequestController = new AbortController();
    resetProjectActionButtons();
    projectAssetsLoading = false;
    if (!preserveWorkspace) resetProjectScopedWorkspace();
    const project = (phase2State.projects || []).find((item) => String(item.id) === nextId);
    phase2State.project_id = nextId;
    phase2State.project_name = project?.name || "";
    phase2State.project_source = project?.source || (nextId.startsWith("local-project-") ? "local" : "server");
    phase2State.standalone_document = false;
    phase2State.brief.id = "";
    phase2State.brief.saved_at = "";
    phase2State.brief.payload_hash = "";
    phase2State.selected_title = "";
    phase2State.master_asset_id = "";
    phase2State.master_asset_revision = null;
    phase2State.output_binding_hash = "";
    phase2State.document_stale = false;
    phase2State.workflow_id = "";
    phase2State.workflow_status = "";
    phase2State.material_ids = [];
    phase2State.variants = [];
    phase2State.academic.records = [];
    phase2State.academic.matrix = [];
    phase2State.academic.evidence = [];
    phase2State.academic.claims = [];
    phase2State.academic.claim_links = [];
    phase2State.academic.claim_comments = [];
    phase2State.academic.coverage = null;
    phase2State.academic.citations = [];
    phase2State.academic.outline = null;
    phase2State.academic.rebuttal = [];
    const restoredDraft = nextId ? restoreProjectDraft(nextId) : false;
    renderProjectOptions();
    renderVariants();
    renderAcademicRecords();
    renderAcademicMatrix();
    renderAcademicEvidence();
    renderAcademicClaimLinks();
    renderAcademicCitations();
    renderAcademicOutline();
    renderAcademicRebuttal();
    updateProjectWorkflowStatus();
    persistPhase2State();
    if (nextId) {
      const pack = project?.default_pack_id || project?.scenario_pack_id;
      if (!restoredDraft && pack && RECIPE_CATALOG[pack]) {
        els.briefScenarioPack.value = pack;
        reconcileTaskContext("scenario_pack", { reloadMethodology: false });
      }
      await loadMethodologyCatalog(false);
      if (projectOperationIsStale(nextId, switchSerial)) return;
      if (!isLocalProject(nextId)) {
        await restoreSelectedServerProject(nextId, switchSerial, true, !restoredDraft);
      }
      if (switchSerial === projectSwitchSerial) toast(`已切换到项目：${phase2State.project_name || nextId}`, "success");
    } else {
      await loadMethodologyCatalog(false);
    }
  }

  function resetProjectScopedWorkspace() {
    const defaults = freshPhase2State();
    appState = freshState();
    phase2State.brief = defaults.brief;
    phase2State.expression = defaults.expression;
    phase2State.selected_title = "";
    phase2State.master_asset_id = "";
    phase2State.master_asset_revision = null;
    phase2State.output_binding_hash = "";
    phase2State.document_stale = false;
    phase2State.workflow_id = "";
    phase2State.workflow_status = "";
    phase2State.material_ids = [];
    phase2State.variants = [];
    phase2State.academic = defaults.academic;
    applyStateToUI();
    els.documentTitle.value = "";
    els.documentEditor.replaceChildren();
    els.generationHero.classList.remove("is-hidden");
    els.documentWorkspace.classList.add("is-hidden");
    applyPhase2StateToUI();
    resetReviewView();
    persistState();
  }

  function openProjectModal() {
    els.projectCreateStatus.textContent = phase2State.local_draft_mode === false
      ? "提交后将写入当前部署的项目服务。"
      : "优先写入项目服务；失败时仅在已开启的本地预览模式中创建草稿项目。";
    els.newProjectName.value = els.topic.value.trim() || "";
    setSelectValue(els.newProjectScenarioPack, phase2State.brief.scenario_pack_id, "gongwen");
    if (!els.projectModal.open) els.projectModal.showModal();
    window.setTimeout(() => els.newProjectName.focus(), 50);
  }

  function closeProjectModal() {
    if (els.projectModal.open) els.projectModal.close();
  }

  async function createProject(event) {
    event.preventDefault();
    const name = els.newProjectName.value.trim();
    if (!name) { els.newProjectName.focus(); return; }
    const body = { name, description: els.newProjectDescription.value.trim(), scenario_pack_id: els.newProjectScenarioPack.value, tags: [] };
    setButtonBusy(els.submitProjectButton, true, "正在创建…");
    els.projectCreateStatus.textContent = "正在写入项目服务…";
    try {
      const result = await progressiveV2("/api/v2/projects", { method: "POST", body }, () => ({ project: { id: `local-project-${Date.now()}`, ...body, default_pack_id: body.scenario_pack_id } }));
      const raw = result.data?.project || result.data;
      if (!raw?.id) throw new Error("项目服务没有返回项目 ID");
      const project = { ...raw, source: result.source };
      phase2State.projects = [...(phase2State.projects || []).filter((item) => String(item.id) !== String(project.id)), project];
      const preserveWorkspace = !phase2State.project_id;
      closeProjectModal();
      await selectProject(String(project.id), { preserveWorkspace });
      toast(result.source === "server" ? "项目已创建并选中" : "项目服务写入失败；已按本地预览模式创建浏览器草稿项目", result.source === "server" ? "success" : "info");
    } catch (error) {
      els.projectCreateStatus.textContent = readError(error, "项目创建失败");
      toast(`项目创建失败：${readError(error, "请检查服务")}`, "error");
    } finally {
      setButtonBusy(els.submitProjectButton, false);
    }
  }

  async function addProjectMaterial() {
    const projectId = requireActiveProject("保存材料");
    if (!projectId) return;
    const operationSerial = projectSwitchSerial;
    const title = els.projectMaterialTitle.value.trim();
    const content = els.projectMaterialContent.value.trim();
    if (!title) { els.projectMaterialTitle.focus(); toast("请填写材料标题", "warning"); return; }
    if (!content) { els.projectMaterialContent.focus(); toast("请填写材料正文", "warning"); return; }
    const body = {
      title,
      content,
      kind: els.projectMaterialKind.value,
      source_url: els.projectMaterialUrl.value.trim(),
      tags: [],
    };
    setButtonBusy(els.addProjectMaterialButton, true, "正在保存…");
    els.projectMaterialStatus.textContent = "正在写入当前项目…";
    try {
      const result = await progressiveV2(`/api/v2/projects/${encodeURIComponent(projectId)}/materials`, { method: "POST", body }, () => ({ material: { id: `local-material-${Date.now()}`, ...body } }));
      if (projectOperationIsStale(projectId, operationSerial)) return;
      const material = result.data?.material || result.data;
      if (!material?.id) throw new Error("材料服务没有返回 material_id");
      phase2State.material_ids = [...new Set([...phase2State.material_ids, String(material.id)])].slice(0, 128);
      invalidateSavedBriefBinding();
      els.projectMaterialContent.value = "";
      els.projectMaterialUrl.value = "";
      els.projectMaterialStatus.textContent = result.source === "server"
        ? `已写入服务端 · material_id ${material.id}`
        : `本地预览 · ${material.id}（服务端未写入）`;
      persistPhase2State();
      updatePhase2Summaries();
      toast(result.source === "server" ? "材料已保存到当前项目" : "材料服务写入失败；已按本地预览模式保留浏览器草稿", result.source === "server" ? "success" : "info");
    } catch (error) {
      if (projectOperationIsStale(projectId, operationSerial, error)) return;
      els.projectMaterialStatus.textContent = `保存失败 · ${readError(error, "请检查服务")}`;
      toast(`材料保存失败：${readError(error, "请检查服务")}`, "error");
    } finally {
      if (!projectOperationIsStale(projectId, operationSerial)) setButtonBusy(els.addProjectMaterialButton, false);
    }
  }

  function workflowKnowledgeSnapshot(projectId) {
    return JSON.stringify({
      project_id: projectId,
      primary_material: currentFactualMaterialText(),
      style_references: (appState.styleReferences || []).map((item) => [
        item.id, item.title, item.source_name, item.url, item.excerpt, item.style_features,
      ]),
    });
  }

  async function workflowManagedMaterialId(projectId, kind, slotKey = "") {
    const input = new TextEncoder().encode(JSON.stringify([projectId, kind, slotKey || kind]));
    let digest;
    if (globalThis.crypto?.subtle) {
      const bytes = new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", input));
      digest = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
    } else {
      digest = Array.from({ length: 8 }, (_, index) => simpleHash(`${index}|${projectId}|${kind}|${slotKey || kind}`)).join("");
    }
    return `workspace-${kind}-${digest}`.slice(0, 128);
  }

  function workflowStyleReferenceSourceKey(reference, index) {
    const referenceId = String(reference?.id || "").trim();
    if (referenceId) return `article-id:${referenceId}`;
    const sourceUrl = String(reference?.url || "").trim();
    if (sourceUrl) return `article-url:${sourceUrl}`;
    return `article-slot:${index + 1}`;
  }

  async function workflowKnowledgeEntries(projectId) {
    const entries = [];
    const primary = currentFactualMaterialText();
    if (primary.length > 500000) throw new Error("主参考材料最多 500000 个字符");
    if (primary) {
      entries.push({
        material_id: await workflowManagedMaterialId(projectId, "source", "primary-material"),
        title: `${els.topic.value.trim() || "当前任务"} · 主参考材料`.slice(0, 500),
        content: primary,
        kind: "source",
        source_url: "",
        tags: ["workspace-managed", "primary-material"],
      });
    }
    for (const [index, reference] of (appState.styleReferences || []).slice(0, 8).entries()) {
      const features = Array.isArray(reference.style_features) ? reference.style_features.filter(Boolean).join("；") : "";
      const content = [reference.excerpt, features ? `写法特征：${features}` : ""].filter(Boolean).join("\n")
        || `仅参考标题结构：${reference.title || "未命名文章"}`;
      entries.push({
        material_id: await workflowManagedMaterialId(
          projectId,
          "style",
          workflowStyleReferenceSourceKey(reference, index),
        ),
        title: `${reference.source_name || "文章来源"}｜${reference.title || "未命名文章"}`.slice(0, 500),
        content: content.slice(0, 500000),
        kind: "style_reference",
        source_url: String(reference.url || "").slice(0, 2000),
        tags: ["workspace-managed", "style-reference"],
      });
    }
    return entries;
  }

  async function ensureWorkflowKnowledge(projectId, operationSerial) {
    const snapshot = workflowKnowledgeSnapshot(projectId);
    const entries = await workflowKnowledgeEntries(projectId);
    if (projectOperationIsStale(projectId, operationSerial) || snapshot !== workflowKnowledgeSnapshot(projectId)) {
      throw new DOMException("写作材料已变化", "AbortError");
    }
    if (isLocalProject(projectId)) return { source: "local", ids: entries.map((item) => `local-material-${item.material_id}`) };
    const results = await Promise.all(entries.map((body) => progressiveV2(
      `/api/v2/projects/${encodeURIComponent(projectId)}/materials`,
      { method: "POST", body },
      () => ({ material: { ...body, id: `local-material-${body.material_id}` } }),
    )));
    if (projectOperationIsStale(projectId, operationSerial) || snapshot !== workflowKnowledgeSnapshot(projectId)) {
      throw new DOMException("写作材料已变化", "AbortError");
    }
    const ids = results.map((result) => String((result.data?.material || result.data)?.id || ""));
    if (ids.some((id) => !id)) throw new Error("项目资料服务没有返回完整 material_id");
    return { source: results.some((result) => result.source !== "server") ? "local" : "server", ids };
  }

  function applyWorkflowManagedMaterialIds(ids) {
    const retained = phase2State.material_ids.filter((id) => !/^workspace-(?:source|style)-/.test(String(id)) && !/^local-material-workspace-(?:source|style)-/.test(String(id)));
    const combined = [...new Set([...retained, ...ids].map(String))];
    if (combined.length > 128) throw new Error("当前简报关联资料超过 128 项，请先移除部分项目资料");
    phase2State.material_ids = combined;
    invalidateSavedBriefBinding();
  }

  async function prepareServerBrief(projectId, operationSerial) {
    syncPhase2StateFromUI();
    validateServerBrief();
    const knowledge = await ensureWorkflowKnowledge(projectId, operationSerial);
    if (projectOperationIsStale(projectId, operationSerial)) return null;
    applyWorkflowManagedMaterialIds(knowledge.ids);
    const brief = validateServerBrief();
    return {
      brief,
      payloadHash: currentBriefBindingHash(brief),
      knowledgeSource: knowledge.source,
    };
  }

  async function persistPreparedBrief(projectId, operationSerial, prepared, { announce = false } = {}) {
    const { brief, payloadHash, knowledgeSource } = prepared;
    const existingBriefId = String(phase2State.brief.id || "");
    const reusableBriefId = existingBriefId && !existingBriefId.startsWith("local-") ? existingBriefId : "";
    const localBrief = { ...brief, id: `local-brief-${Date.now()}` };
    const path = isLocalProject(projectId) ? "/api/v2/projects/LOCAL/briefs" : `/api/v2/projects/${encodeURIComponent(projectId)}/briefs`;
    const requestBody = reusableBriefId ? { ...brief, brief_id: reusableBriefId } : brief;
    const result = knowledgeSource === "server"
      ? await progressiveV2(path, { method: "POST", body: requestBody }, () => ({ brief: localBrief }))
      : { data: { brief: localBrief }, source: "local" };
    if (projectOperationIsStale(projectId, operationSerial) || payloadHash !== currentBriefBindingHash(brief)) return null;
    const normalized = result.data?.brief || result.data?.item || result.data || {};
    if (!normalized.id) throw new Error("简报服务没有返回 brief_id");
    phase2State.brief.id = String(normalized.id);
    phase2State.brief.saved_at = new Date().toISOString();
    phase2State.brief.payload_hash = payloadHash;
    els.briefStatus.textContent = result.source === "server" ? "已保存到当前项目服务" : "本地预览 · 服务端未写入";
    persistPhase2State();
    updatePhase2Summaries();
    if (announce) {
      toast(result.source === "server" ? "任务简报已保存到当前项目" : "服务写入未完成；已按你开启的本地预览模式保存浏览器草稿", result.source === "server" ? "success" : "info");
    }
    return { brief: normalized, source: result.source };
  }

  async function runProjectWorkflow() {
    if (!requireModelConnection({ project: true })) return;
    const projectId = requireActiveProject("生成项目母稿");
    if (!projectId) return;
    const operationSerial = projectSwitchSerial;
    let workflowInputOperation = captureInputOperation(projectId);
    setButtonBusy(els.runProjectWorkflowButton, true, "正在执行…");
    els.projectWorkflowStatus.textContent = "正在同步当前材料与写作设置…";
    try {
      const prepared = await prepareServerBrief(projectId, operationSerial);
      if (!prepared) return;
      workflowInputOperation = captureInputOperation(projectId);
      if (prepared.knowledgeSource !== "server") {
        if (settings.mode === "api") throw new Error("项目材料尚未同步，真实模型工作流未启动。请连接项目服务后重试。");
        phase2State.workflow_id = `local-workflow-${Date.now()}`;
        phase2State.workflow_status = "local_preview";
        const generated = await generateDocument();
        if (projectOperationIsStale(projectId, operationSerial)) return;
        if (!generated) return;
        if (!documentPlainText()) throw new Error("本地预览母稿生成未完成");
        phase2State.master_asset_id = `local-asset-${Date.now()}`;
        phase2State.output_binding_hash = currentBriefBindingHash();
        els.projectWorkflowStatus.textContent = "本地预览已完成 · 服务端工作流与资产未写入";
        persistPhase2State();
        toast("项目服务暂未写入；已生成浏览器母稿", "info");
        return;
      }
      const hasReusableBrief = phase2State.brief.id
        && !String(phase2State.brief.id).startsWith("local-")
        && phase2State.brief.payload_hash === prepared.payloadHash;
      if (!hasReusableBrief) {
        const saved = await persistPreparedBrief(projectId, operationSerial, prepared);
        if (!saved) throw new Error("任务简报尚未保存");
        if (saved.source !== "server") {
          if (settings.mode === "api") throw new Error("任务简报尚未保存到服务端，真实模型工作流未启动。");
          phase2State.workflow_id = `local-workflow-${Date.now()}`;
          phase2State.workflow_status = "local_preview";
          const generated = await generateDocument();
          if (projectOperationIsStale(projectId, operationSerial)) return;
          if (!generated) return;
          if (!documentPlainText()) throw new Error("本地预览母稿生成未完成");
          phase2State.master_asset_id = `local-asset-${Date.now()}`;
          phase2State.output_binding_hash = currentBriefBindingHash();
          els.projectWorkflowStatus.textContent = "本地预览已完成 · 服务端工作流与资产未写入";
          persistPhase2State();
          toast("项目服务暂未写入；已生成浏览器母稿", "info");
          return;
        }
      }
      if (projectOperationIsStale(projectId, operationSerial)) return;
      const brief = { ...serverGenerationBriefPayload(), brief_id: phase2State.brief.id };
      const inputOperation = captureInputOperation(projectId);
      workflowInputOperation = inputOperation;
      els.projectWorkflowStatus.textContent = "正在创建项目工作流…";
      const created = await progressiveV2(`/api/v2/projects/${encodeURIComponent(projectId)}/workflows`, {
        method: "POST",
        body: { ...brief, live: settings.mode === "api", auto_review: true, requested_exports: [] },
      }, () => ({ brief_id: phase2State.brief.id, workflow: { id: `local-workflow-${Date.now()}`, brief_id: phase2State.brief.id, status: "local_preview" } }));
      if (inputOperationIsStale(inputOperation)) return;
      const workflow = created.data?.workflow || created.data;
      if (!workflow?.id) throw new Error("工作流服务没有返回 workflow_id");
      const returnedBriefId = String(created.data?.brief_id || workflow.brief_id || "");
      if (!returnedBriefId) throw new Error("工作流服务没有返回 brief_id");
      if (created.source === "server" && returnedBriefId !== String(phase2State.brief.id)) throw new Error("工作流没有绑定当前任务简报");
      phase2State.brief.id = returnedBriefId;
      phase2State.brief.payload_hash = currentBriefBindingHash();
      phase2State.workflow_id = String(workflow.id);
      phase2State.workflow_status = String(workflow.status || "created");
      if (created.source === "local") {
        const generated = await generateDocument();
        if (projectOperationIsStale(projectId, operationSerial)) return;
        if (!generated) return;
        if (!documentPlainText()) throw new Error("本地预览母稿生成未完成");
        phase2State.master_asset_id = `local-asset-${Date.now()}`;
        phase2State.workflow_status = "local_preview";
        els.projectWorkflowStatus.textContent = "本地预览已完成 · 服务端工作流与资产未写入";
        persistPhase2State();
        toast("工作流服务执行失败；已按本地预览模式生成浏览器母稿", "info");
        return;
      }
      els.projectWorkflowStatus.textContent = `工作流 ${workflow.id} 已创建，正在运行…`;
      const ran = await apiRequest(`/api/v2/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(workflow.id)}/run`, { method: "POST", body: { mode: "sync" } });
      if (inputOperationIsStale(inputOperation)) return;
      const completed = ran?.workflow || ran;
      const completedStatus = String(completed?.status || "");
      phase2State.workflow_status = completedStatus || "unknown";
      if (completedStatus === "waiting_review") {
        els.projectWorkflowStatus.textContent = `工作流 ${workflow.id} 等待人工复核`;
        persistPhase2State();
        toast("工作流已暂停，等待人工复核后再继续", "warning");
        return;
      }
      if (completedStatus !== "succeeded") throw new Error(completedStatus === "cancelled" ? "工作流已取消" : completedStatus === "failed" ? "工作流执行失败" : `工作流尚未完成（${completedStatus || "状态未知"}）`);
      const outputAssetId = String(completed?.output_asset_id || "");
      if (!outputAssetId) throw new Error("已完成的工作流没有返回 output_asset_id");
      const asset = await syncProjectAssets(
        false,
        true,
        outputAssetId,
        projectId,
        inputOperation,
        String(phase2State.brief.id || ""),
        true,
      );
      if (!asset?.id || String(asset.id) !== outputAssetId) throw new Error("工作流输出母稿尚未成功载入");
      els.projectWorkflowStatus.textContent = `工作流 ${phase2State.workflow_status} · 母稿 ${asset.id}`;
      persistPhase2State();
      toast("项目工作流已完成，母稿已载入", "success");
    } catch (error) {
      if (projectOperationIsStale(projectId, operationSerial, error)
        || inputOperationIsStale(workflowInputOperation, error)) return;
      phase2State.workflow_status = "failed";
      els.projectWorkflowStatus.textContent = `工作流失败 · ${readError(error, "请检查项目服务")}`;
      toast(`项目工作流失败：${readError(error, "请检查服务")}`, "error");
    } finally {
      if (!projectOperationIsStale(projectId, operationSerial)) {
        setButtonBusy(els.runProjectWorkflowButton, false);
        if (phase2State.workflow_status !== "failed") updateProjectWorkflowStatus();
      }
    }
  }

  async function syncProjectAssets(
    notify = false,
    loadIntoEditor = false,
    preferredAssetId = "",
    expectedProjectId = phase2State.project_id,
    expectedInputOperation = null,
    expectedBriefId = "",
    bindToCurrentBrief = true,
  ) {
    const projectId = String(expectedProjectId || "");
    if (!projectId || isLocalProject(projectId)) return null;
    const operationSerial = expectedInputOperation?.projectSerial ?? projectSwitchSerial;
    const responseIsStale = () => projectOperationIsStale(projectId, operationSerial)
      || (expectedInputOperation && inputOperationIsStale(expectedInputOperation))
      || (expectedBriefId && String(phase2State.brief.id || "") !== String(expectedBriefId));
    try {
      let items = [];
      let preferred = preferredAssetId ? { id: String(preferredAssetId) } : null;
      if (!preferred) {
        const response = await readAllPages(
          (offset, limit) => `/api/v2/projects/${encodeURIComponent(projectId)}/assets?limit=${limit}&offset=${offset}`,
          "资产服务",
        );
        if (responseIsStale()) return null;
        items = response.items;
        if (items.some((item) => !item || typeof item !== "object" || !String(item.id || "").trim())) throw new Error("资产列表包含缺少 ID 的条目");
        preferred = items.find((item) => !item.parent_asset_id) || items[0];
      }
      if (!preferred?.id) return null;
      const detailResponse = await apiRequest(`/api/v2/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(preferred.id)}?chunk_size=20000`);
      if (responseIsStale()) return null;
      const asset = detailResponse?.asset || detailResponse;
      if (!workspaceContext.assetMatchesBinding(asset, {
        assetId: String(preferred.id),
        projectId,
        briefId: expectedBriefId,
        requireBriefId: true,
      })) throw new Error(expectedBriefId ? "资产与当前任务简报不匹配" : "资产详情缺少可追溯的简报关系");
      if (!Array.isArray(asset.blocks) || !textFromAsset(asset)) throw new Error("资产详情缺少可用正文块");
      if (responseIsStale()) return null;
      if (loadIntoEditor) {
        applyServerAsset(asset, { bindToCurrentBrief, execution: detailResponse.execution });
      } else {
        phase2State.master_asset_id = bindToCurrentBrief ? String(asset.id) : "";
        phase2State.master_asset_revision = bindToCurrentBrief ? Number(asset.current_revision || preferred.current_revision) || null : null;
      }
      updateProjectWorkflowStatus();
      updatePhase2Summaries();
      persistPhase2State();
      if (notify) toast(preferredAssetId ? "工作流输出母稿已同步" : `已同步 ${items.length} 项文字资产`, "success");
      return asset;
    } catch (error) {
      if (notify && error?.name !== "AbortError") toast(`资产同步失败：${readError(error, "请检查服务")}`, "error");
      return null;
    }
  }

  function applyServerAsset(asset, { bindToCurrentBrief = true, execution = null } = {}) {
    const assetId = String(asset?.id || "");
    const assetRevision = Number(asset?.current_revision) || null;
    const title = String(asset?.title || els.topic.value.trim() || "项目母稿");
    const text = textFromAsset(asset);
    const assetDocumentType = String(asset?.content_type || "").trim();
    if (assetDocumentType) {
      ensureDocumentTypeOption(assetDocumentType);
      els.documentType.value = assetDocumentType;
      reconcileTaskContext("document_type", { invalidate: false, persist: false });
    }
    appState.document = { title, html: "", candidates: [], outline: [], execution: executionMode.execution(execution) };
    renderDocumentExecution();
    els.documentTitle.value = title;
    els.documentEditor.replaceChildren();
    const blocks = Array.isArray(asset?.blocks) ? asset.blocks : [];
    if (blocks.length) {
      blocks.filter((block) => block && block.kind !== "title").forEach((block) => {
        const tag = block.kind === "heading" ? `h${Math.min(4, Math.max(2, Number(block.heading_level) || 2))}` : "p";
        const node = document.createElement(tag); node.textContent = normalizeGeneratedPunctuation(block.text); els.documentEditor.append(node);
      });
    } else {
      text.split(/\n{2,}|\r?\n/).map((item) => item.trim()).filter(Boolean).forEach((paragraphText) => {
        const node = document.createElement("p"); node.textContent = paragraphText; els.documentEditor.append(node);
      });
    }
    appState.document.html = sanitizeHtml(els.documentEditor.innerHTML);
    appState.document.outline = $$('h2, h3', els.documentEditor).map((heading) => ({
      heading: heading.textContent || "未命名章节",
      content: "",
    }));
    phase2State.master_asset_id = bindToCurrentBrief ? assetId : "";
    phase2State.master_asset_revision = bindToCurrentBrief ? assetRevision : null;
    phase2State.document_stale = !bindToCurrentBrief;
    phase2State.output_binding_hash = bindToCurrentBrief ? currentBriefBindingHash() : "";
    els.generationHero.classList.add("is-hidden");
    els.documentWorkspace.classList.remove("is-hidden");
    invalidateDocumentDerivedState();
    resetReviewView();
    renderCandidates();
    renderOutline();
    renderDocumentContextStatus();
    updateCounts();
    updatePhase2Summaries();
    scheduleSave();
    schedulePhase2Save();
  }

  function updateProjectWorkflowStatus() {
    if (!els.projectWorkflowStatus) return;
    if (phase2State.document_stale && documentPlainText()) {
      els.projectWorkflowStatus.textContent = "任务设置已更新 · 当前编辑区保留上一版草稿供对照，请重新生成后再作为项目母稿";
      return;
    }
    if (!phase2State.project_id) {
      els.projectWorkflowStatus.textContent = phase2State.standalone_document
        ? "当前为独立文稿 · 不写入任何项目；选择项目后再生成项目母稿"
        : "选择项目后，可将简报、标题、母稿、审校和交付串成真实服务闭环。";
      return;
    }
    if (phase2State.master_asset_id) {
      const location = isLocalProject() || phase2State.master_asset_id.startsWith("local-") ? "本地预览" : "服务端资产";
      els.projectWorkflowStatus.textContent = `${phase2State.project_name || "当前项目"} · ${location} ${phase2State.master_asset_id}`;
      return;
    }
    els.projectWorkflowStatus.textContent = `${phase2State.project_name || "当前项目"}已就绪 · 保存简报或生成项目母稿`;
  }

  function renderDocumentContextStatus() {
    if (!els.documentContextStatus) return;
    els.documentContextStatus.textContent = phase2State.document_stale
      ? "上一版草稿 · 待重生成"
      : phase2State.standalone_document ? "独立文稿 · 未关联项目" : "草稿";
    els.documentContextStatus.classList.toggle("is-stale", Boolean(phase2State.document_stale));
    els.documentWorkspace.classList.toggle("has-stale-context", Boolean(phase2State.document_stale));
  }

  function setV2ServiceState(state) {
    v2ServiceState = state;
    const labels = {
      checking: "正在识别服务能力",
      connected: "第二阶段服务已连接",
      local: "本地预览 · 渐进接入",
      waiting: "输入访问令牌后检测",
    };
    els.v2CapabilityState.className = `api-state is-${state}`;
    els.v2CapabilityState.replaceChildren();
    const dot = document.createElement("i");
    els.v2CapabilityState.append(dot, document.createTextNode(labels[state] || labels.local));
    els.settingsV2Title.textContent = state === "connected" ? "第二阶段服务已连接" : state === "checking" ? "正在检测第二阶段服务" : "渐进增强模式";
    els.settingsV2Summary.textContent = state === "connected"
      ? "项目、文字资产、知识检索和学术研究将优先使用 /api/v2/* 服务。"
      : phase2State.local_draft_mode !== false
        ? "项目服务暂未连接；已明确启用本地预览，所有降级结果都会标注为服务端未写入。"
        : "项目服务暂未连接；本地预览已关闭，写入失败会直接显示错误。";
  }

  function selectExpressionFocus(focus, persist = true) {
    const valid = new Set(["title", "opening", "section_heading", "topic_sentence"]);
    const nextFocus = valid.has(focus) ? focus : "title";
    const changed = phase2State.expression.focus !== nextFocus;
    phase2State.expression.focus = nextFocus;
    $$("[data-expression-focus]").forEach((button) => {
      const active = button.dataset.expressionFocus === nextFocus;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    });
    const placeholders = {
      title: "例如：用三组排比，体现为民、务实、担当",
      opening: "例如：第一句亮明判断，随后交代背景和任务",
      section_heading: "例如：四个小标题结构平行、语义递进",
      topic_sentence: "例如：每段首句先亮明判断，再展开依据和行动",
    };
    const generic = { title: "例如：具体、清晰，准确反映问题和价值", opening: "例如：结论先行，区分背景与证据", section_heading: "例如：按问题、方法、证据组织层级", topic_sentence: "例如：先给可核验判断，再说明依据与边界" };
    els.expressionInstruction.placeholder = currentScenario().id === "gongwen" ? placeholders[nextFocus] : generic[nextFocus];
    if (changed && persist) {
      phase2State.expression.results = [];
      renderExpressionResults();
      schedulePhase2Save();
    }
  }

  async function generateExpressions() {
    const topic = els.topic.value.trim() || els.academicTitle.value.trim();
    if (!topic) {
      els.topic.focus();
      toast("请先填写写作主题", "warning");
      return;
    }
    syncPhase2StateFromUI();
    let brief;
    try { validateServerBrief(); brief = serverGenerationBriefPayload(); }
    catch (error) { toast(readError(error, "请先完善任务简报"), "warning"); return; }
    const projectId = requireActiveProject("生成表达候选");
    if (!projectId) return;
    const operationSerial = projectSwitchSerial;
    const requestSerial = ++expressionRequestSerial;
    const inputOperation = captureInputOperation(projectId);
    const focus = phase2State.expression.focus;
    const count = phase2State.expression.count;
    const body = {
      ...brief,
      count,
      headline_kind: focus,
      formula_ids: [],
    };
    if (phase2State.expression.instruction) body.constraints = boundedTextList([...body.constraints, phase2State.expression.instruction], 500, 32);
    const path = `/api/v2/projects/${encodeURIComponent(projectId)}/headlines`;
    setButtonBusy(els.generateExpressionsButton, true, "正在推演…");
    try {
      const result = await progressiveV2(path, { method: "POST", body }, () => ({ items: localExpressionCandidates(focus, count) }));
      if (requestSerial !== expressionRequestSerial || inputOperationIsStale(inputOperation)) return;
      let candidates = normalizeExpressionCandidates(result.data);
      if (!candidates.length) {
        if (result.source === "server") throw new Error("标题服务没有返回可用候选");
        candidates = localExpressionCandidates(focus, count);
      }
      phase2State.expression.results = candidates.slice(0, count);
      renderExpressionResults();
      persistPhase2State();
      toast(result.source === "server" ? "表达候选已由项目服务生成" : "服务生成未完成；已按本地预览模式生成候选", result.source === "server" ? "success" : "info");
    } catch (error) {
      if (requestSerial !== expressionRequestSerial || inputOperationIsStale(inputOperation, error)) return;
      toast(readError(error, "表达候选生成未完成"), "error");
    } finally {
      if (requestSerial === expressionRequestSerial && !projectOperationIsStale(projectId, operationSerial)) setButtonBusy(els.generateExpressionsButton, false);
    }
  }

  function normalizeExpressionCandidates(data) {
    const raw = data?.candidate_batch?.candidates || data?.candidates || data?.items || data?.results || data?.headlines || data?.outputs || [];
    if (!Array.isArray(raw)) return [];
    return raw.map((item) => {
      if (typeof item === "string") return item.trim();
      return String(item?.title || item?.text || item?.content || item?.output || "").trim();
    }).filter(Boolean);
  }

  function localExpressionCandidates(focus, count) {
    if (currentScenario().id !== "gongwen") return scenarioWorkspace.expressionCandidates(currentScenario().id, focus, {
      topic: els.topic.value.trim(), goal: els.purpose.value.trim(), audience: els.audience.value.trim(), headings: activeRecipeContext().headings,
    }, count);
    const topic = (els.topic.value.trim() || els.academicTitle.value.trim() || "重点工作").replace(/[，。！？；:：]+$/g, "");
    const goal = (els.purpose.value.trim() || "推动任务落地见效").replace(/[，。！？；:：]+$/g, "");
    const audience = els.audience.value.trim() || "干部群众";
    const keywordList = phase2State.brief.keywords.split(/[，,、;；\s]+/).filter(Boolean);
    const keywords = keywordList.slice(0, 3);
    const trio = keywords.length >= 3 ? keywords : ["站稳立场", "实干担当", "务求实效"];
    const templates = {
      title: [
        `把准“方向盘”、用好“指挥棒”、守住“实效关”——以${topic}书写为民答卷`,
        `一看立场、二看担当、三看实效、四看口碑：在${topic}中校准行动坐标`,
        `不慕虚名、不务虚功、不走捷径，以${topic}推动${goal}`,
        `以${trio[0]}定方向，以${trio[1]}破难题，以${trio[2]}验成色`,
        `从“做了什么”到“群众得到什么”：${topic}的实践之问`,
        `谋在实处、干在要处、落在细处——扎实推进${topic}`,
        `既看“显绩”更看“潜绩”，既重“当下”更利“长远”——关于${topic}的思考`,
        `答好${topic}“四道题”：为何做、为谁做、怎么做、谁评价`,
      ],
      opening: [
        `${topic}，表面看是一项具体工作，实质上检验的是立场、方法与担当。`,
        `怎么看${topic}，决定着怎么谋、怎么干，也决定着${audience}最终能得到什么。`,
        `衡量${topic}的成色，既要看过程中的行动力度，更要看落地后的实际效果。`,
        `开局之要，在于把方向想清；成事之基，在于把任务做实；落脚之处，在于让${audience}有感。`,
        `当前，${topic}进入由“搭框架”向“见实效”深化的关键阶段。`,
      ],
      topic_sentence: [
        `一要把准方向，在${topic}中始终站稳根本立场。`,
        `二要做实过程，以钉钉子精神把${goal}落到具体行动。`,
        `三要检验成效，把${audience}的感受作为衡量工作的标尺。`,
        `四要着眼长远，既解决当下问题，也夯实持续发展的基础。`,
        `认识上再深化，解决“为什么干”的问题。`,
        `行动上再聚焦，解决“抓什么干”的问题。`,
        `责任上再压实，解决“由谁来干”的问题。`,
        `评价上再校准，解决“干得怎样”的问题。`,
      ],
      section_heading: [
        "一、把准方向，在站稳立场中校准工作坐标",
        "二、压实责任，在攻坚克难中提升行动质效",
        "三、做实过程，在闭环推进中破解实际问题",
        "四、检验成色，在群众评价中回答实践之问",
        `以${trio[0]}明方向，以${trio[1]}抓落实，以${trio[2]}验成效`,
        `从目标设定到过程管理，从任务落地到成效评价`,
      ],
    };
    const source = templates[focus] || templates.title;
    return Array.from({ length: count }, (_, index) => source[index % source.length]);
  }

  function renderExpressionResults() {
    const results = Array.isArray(phase2State.expression.results) ? phase2State.expression.results : [];
    els.expressionResults.replaceChildren();
    els.expressionResults.classList.toggle("is-empty", !results.length);
    if (!results.length) {
      const empty = document.createElement("div");
      const strong = document.createElement("strong"); strong.textContent = "选择一个表达位置";
      const span = document.createElement("span"); span.textContent = "砚章会结合任务目标、阅读对象和关键词给出成组候选。";
      empty.append(strong, span); els.expressionResults.append(empty); return;
    }
    results.forEach((text, index) => {
      const card = document.createElement("article"); card.className = "expression-result-card";
      const number = document.createElement("span"); number.textContent = String(index + 1).padStart(2, "0");
      const copy = document.createElement("p"); copy.textContent = text;
      const action = document.createElement("button"); action.type = "button"; action.className = "mini-button";
      action.textContent = phase2State.expression.focus === "title" ? "采用为标题" : "放入母稿";
      action.addEventListener("click", () => applyExpression(text));
      card.append(number, copy, action); els.expressionResults.append(card);
    });
  }

  function applyExpression(text) {
    openSuiteView("projects");
    if (phase2State.expression.focus === "title") {
      selectTitle(text);
      els.documentTitle.value = text;
      scheduleSave();
      toast("已采用为母稿标题", "success");
      return;
    }
    const contentNode = document.createElement(phase2State.expression.focus === "section_heading" ? "h2" : "p"); contentNode.textContent = text;
    if (phase2State.expression.focus === "opening" && els.documentEditor.firstChild) {
      els.documentEditor.insertBefore(contentNode, els.documentEditor.firstChild);
    } else {
      els.documentEditor.append(contentNode);
    }
    els.generationHero.classList.add("is-hidden");
    els.documentWorkspace.classList.remove("is-hidden");
    handleDocumentInput();
    focusProjectControl("documentEditor");
    toast("表达已放入母稿，可继续编辑", "success");
  }

  async function generateVariants() {
    if (!requireModelConnection({ project: true })) return;
    syncPhase2StateFromUI();
    const content = documentPlainText();
    if (!content) { toast("请先生成或输入母稿正文", "warning"); return; }
    const channels = $$('input[type="checkbox"]:checked', els.variantChannels).map((input) => input.value);
    if (!channels.length) { toast("请至少选择一个交付渠道", "warning"); return; }
    const projectId = requireActiveProject("生成渠道变体");
    if (!projectId) return;
    const operationSerial = projectSwitchSerial;
    const inputOperation = captureInputOperation(projectId);
    setButtonBusy(els.generateVariantsButton, true, "正在生成…");
    try {
      const master = await ensureMasterAsset();
      if (inputOperationIsStale(inputOperation)) return;
      if (settings.mode === "api" && master.source !== "server") throw new Error("项目服务未就绪，真实模型变体未启动。请连接项目服务后重试。");
      const variants = [];
      let usedLocal = master.source !== "server";
      for (const channel of channels) {
        if (master.source !== "server") { variants.push(localVariant(channel, content)); continue; }
        const lengthHint = { auto: "", short: "目标篇幅 300—500 字。", medium: "目标篇幅 800—1200 字。", long: "目标篇幅 1500—2500 字。" }[els.variantLength.value] || "";
        const instruction = [lengthHint, els.variantInstruction.value.trim()].filter(Boolean).join(" ");
        const result = await progressiveV2(`/api/v2/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(master.id)}/variants`, { method: "POST", body: {
          target_channel: channel,
          instruction,
          source_revision: phase2State.master_asset_revision || undefined,
          live: settings.mode === "api",
        } }, () => ({ asset: localVariant(channel, content) }));
        if (inputOperationIsStale(inputOperation)) return;
        const rawAsset = result.data?.asset || result.data;
        if (result.source === "server") {
          if (!responseValidators?.validateVariantAsset?.(rawAsset, {
            expectedChannel: channel,
            expectedParentAssetId: master.id,
          }) || String(result.data?.source_asset_id || "") !== String(master.id)) {
            throw new Error(`渠道 ${channel} 的服务响应缺少可追溯的文字资产`);
          }
        }
        const normalized = normalizeVariants({ items: [{ ...rawAsset, execution: result.data?.execution || rawAsset.execution }] });
        if (!normalized.length && result.source === "server") throw new Error(`渠道 ${channel} 的服务响应缺少有效文字资产`);
        variants.push(...(normalized.length ? normalized : [localVariant(channel, content)]));
        if (result.source !== "server") usedLocal = true;
      }
      phase2State.variants = variants;
      renderVariants();
      persistPhase2State();
      toast(usedLocal ? "部分服务写入未完成；已按本地预览模式补齐渠道草稿" : "渠道变体已保存为项目文字资产", usedLocal ? "info" : "success");
    } catch (error) {
      if (projectOperationIsStale(projectId, operationSerial, error)
        || inputOperationIsStale(inputOperation, error)) return;
      toast(readError(error, "渠道变体生成未完成"), "error");
    } finally {
      if (!projectOperationIsStale(projectId, operationSerial)) setButtonBusy(els.generateVariantsButton, false);
    }
  }

  async function ensureMasterAsset() {
    const projectId = requireActiveProject("保存母稿资产");
    if (!projectId) throw new Error("请先选择项目");
    const operationSerial = projectSwitchSerial;
    invalidateSavedBriefBinding();
    if (phase2State.document_stale) {
      const error = new Error("当前保留的是上一版草稿，请按新任务重新生成正文，再生成变体、审校或交付");
      error.name = "StaleDocumentError";
      throw error;
    }
    if (phase2State.master_asset_id && !phase2State.master_asset_id.startsWith("local-") && !isLocalProject(projectId)) {
      await saveMasterRevisionToServer(projectId, phase2State.master_asset_id);
      return { id: phase2State.master_asset_id, source: "server" };
    }
    const prepared = await prepareServerBrief(projectId, operationSerial);
    if (!prepared) throw new DOMException("项目已切换", "AbortError");
    const hasReusableBrief = phase2State.brief.id
      && !String(phase2State.brief.id).startsWith("local-")
      && phase2State.brief.payload_hash === prepared.payloadHash;
    if (!hasReusableBrief) {
      const saved = await persistPreparedBrief(projectId, operationSerial, prepared);
      if (!saved) throw new Error("任务简报尚未保存");
    }
    if (isLocalProject(projectId) || String(phase2State.brief.id).startsWith("local-")) {
      phase2State.master_asset_id = phase2State.master_asset_id || `local-asset-${Date.now()}`;
      return { id: phase2State.master_asset_id, source: "local" };
    }
    const inputOperation = captureInputOperation(projectId);
    const expectedBriefId = String(phase2State.brief.id || "");
    const result = await progressiveV2(`/api/v2/projects/${encodeURIComponent(projectId)}/assets`, { method: "POST", body: {
      brief_id: expectedBriefId,
      title: els.documentTitle.value.trim() || els.topic.value.trim() || undefined,
      live: false,
    } }, () => ({ asset: { id: `local-asset-${Date.now()}` } }));
    if (inputOperationIsStale(inputOperation)) throw new DOMException("写作输入已变化", "AbortError");
    const asset = result.data?.asset || result.data?.item || result.data || {};
    if (!asset.id) throw new Error("母稿服务没有返回 asset_id");
    if (result.source === "server" && !workspaceContext.assetMatchesBinding(asset, {
      projectId,
      briefId: expectedBriefId,
      requireBriefId: true,
    })) throw new Error("母稿服务返回的资产与当前任务简报不匹配");
    phase2State.master_asset_id = String(asset.id);
    phase2State.master_asset_revision = Number(asset.current_revision) || null;
    if (result.source === "server" && documentPlainText()) await saveMasterRevisionToServer(projectId, phase2State.master_asset_id);
    return { id: phase2State.master_asset_id, source: result.source };
  }

  async function saveMasterRevisionToServer(projectId, assetId) {
    const blocks = documentBlocksForV2();
    if (!blocks.length || isLocalProject(projectId) || String(assetId).startsWith("local-")) return null;
    const body = {
      blocks,
      note: "浏览器工作台保存的母稿修订",
      expected_revision: phase2State.master_asset_revision || undefined,
      title: els.documentTitle.value.trim() || undefined,
      status: "draft",
    };
    const operation = {
      projectId: String(projectId),
      projectSerial: projectSwitchSerial,
      assetId: String(assetId),
      assetRevision: Number(phase2State.master_asset_revision || 0),
      editorHash: simpleHash(JSON.stringify({ title: body.title || "", blocks })),
    };
    const response = await apiRequest(`/api/v2/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(assetId)}/revisions`, { method: "POST", body });
    const revision = response?.revision || response;
    const version = Number(revision?.version);
    if (!revision || typeof revision !== "object" || !Number.isInteger(version) || version < 1) throw new Error("修订服务没有返回有效版本");
    if (revision.asset_id !== undefined && String(revision.asset_id) !== String(assetId)) throw new Error("修订服务返回了不匹配的 asset_id");
    if (revision.project_id !== undefined && String(revision.project_id) !== String(projectId)) throw new Error("修订服务返回了不匹配的 project_id");
    const currentEditorHash = simpleHash(JSON.stringify({
      title: els.documentTitle.value.trim(),
      blocks: documentBlocksForV2(),
    }));
    if (projectOperationIsStale(operation.projectId, operation.projectSerial)
      || String(phase2State.master_asset_id || "") !== operation.assetId
      || Number(phase2State.master_asset_revision || 0) !== operation.assetRevision
      || currentEditorHash !== operation.editorHash) return null;
    phase2State.master_asset_revision = version;
    return revision;
  }

  function documentBlocksForV2() {
    const blocks = [];
    const title = els.documentTitle.value.trim();
    if (title) blocks.push({ id: `block-${simpleHash(`title|${title}`)}`, kind: "title", order: 0, text: title, locked: false, knowledge_item_ids: [], evidence_ids: [] });
    [...els.documentEditor.children].forEach((node, index) => {
      const text = String(node.textContent || "").trim();
      if (!text) return;
      const headingMatch = node.tagName.match(/^H([1-6])$/);
      const kind = headingMatch ? "heading" : ["UL", "OL", "LI"].includes(node.tagName) ? "list" : "paragraph";
      const block = { id: `block-${simpleHash(`${index}|${kind}|${text}`)}`, kind, order: blocks.length, text, locked: false, knowledge_item_ids: serverMaterialIds(), evidence_ids: [] };
      if (headingMatch) block.heading_level = Number(headingMatch[1]);
      blocks.push(block);
    });
    if (!blocks.length && documentPlainText()) blocks.push({ id: `block-${simpleHash(documentPlainText())}`, kind: "paragraph", order: 0, text: documentPlainText(), locked: false, knowledge_item_ids: serverMaterialIds(), evidence_ids: [] });
    return blocks;
  }

  function normalizeVariants(data) {
    const raw = data?.variants || data?.items || data?.assets || [];
    if (!Array.isArray(raw)) return [];
    return raw.map((item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return null;
      const content = textFromAsset(item);
      const id = String(item.id || "").trim();
      const channel = String(item.channel || "").trim();
      const title = String(item.title || "").trim();
      const parentAssetId = String(item.parent_asset_id || "").trim();
      if (!id || !channel || !title || !content || !parentAssetId) return null;
      return {
        id,
        channel,
        title,
        content,
        parent_asset_id: parentAssetId,
        execution: executionMode.execution(item.execution),
      };
    }).filter(Boolean);
  }

  function textFromAsset(item) {
    if (typeof item?.content === "string") return normalizeGeneratedPunctuation(item.content).trim();
    if (typeof item?.text === "string") return normalizeGeneratedPunctuation(item.text).trim();
    if (Array.isArray(item?.blocks)) return normalizeGeneratedPunctuation(item.blocks.map((block) => block?.text || block?.content || "").filter(Boolean).join("\n\n")).trim();
    return "";
  }

  function normalizeGeneratedPunctuation(value) {
    return String(value || "").replace(/(写作时同时遵循：[^\n<]*?)。{2,}/g, "$1。");
  }

  function localVariant(channel, content) {
    const title = els.documentTitle.value.trim() || els.topic.value.trim() || "工作材料";
    const normalized = content.replace(/\n{3,}/g, "\n\n").trim();
    const targetLength = els.variantLength.value;
    const limits = { short: 500, medium: 1200, long: 2500, auto: 1500 };
    const clipped = normalized.length > limits[targetLength] ? `${normalized.slice(0, limits[targetLength])}……` : normalized;
    const transformations = {
      document: { title: `文档｜${title}`, content: `【母稿摘录】\n${clipped}\n\n【待整理】按交付目的确认结构与来源说明；缺失信息保留待补标记。` },
      email: { title: `工作邮件｜${title}`, content: `主题：${title}\n\n各位同事：\n\n${firstSentence(normalized)}\n\n${clipped}\n\n请按母稿明确的责任与时限推进，并及时反馈进展。` },
      meeting: { title: `会议材料｜${title}`, content: `会议议题：${title}\n\n一、核心结论\n${firstSentence(normalized)}\n\n二、讨论要点\n${clipped}\n\n三、议定事项\n请依据母稿补充责任主体、完成时限和跟踪方式。` },
      presentation: { title: `汇报演示｜${title}`, content: `封面｜${title}\n\n01 核心判断\n${firstSentence(normalized)}\n\n02 事实与进展\n${clipped}\n\n03 下一步行动\n按母稿中的责任、节点与证据逐项呈现。` },
      web: { title: `网站稿件｜${title}`, content: `${title}\n\n${clipped}\n\n【待确认：发布对象、导语和来源说明】` },
      social: { title: `社交媒体｜${title}`, content: `一图读懂｜${title}\n\n✅ 为什么做\n${firstSentence(normalized)}\n\n✅ 做了什么\n${clipped}\n\n✅ 下一步怎么干\n以母稿明确的责任与时限为准。` },
      academic: { title: `研究文本｜${title}`, content: `【摘要整理框架，待原文证据补齐】\n研究问题：${title}\n方法：【待补：以原始研究记录为准】\n结果：【待补：仅填写有数据和引用依据的发现】\n结论：【待补：说明适用范围与局限】\n\n【母稿摘录，尚未核验为学术证据】\n${clipped}\n\n关键词：${phase2State.brief.keywords || "【待补】"}` },
    };
    const item = transformations[channel] || { title: channelLabel(channel), content: clipped };
    return { id: `local-${channel}-${Date.now()}`, channel, ...item, parent_asset_id: phase2State.master_asset_id || "", execution: executionMode.execution({ mode: "local" }) };
  }

  function firstSentence(text) {
    return String(text || "").split(/[。！？\n]/).map((item) => item.trim()).find(Boolean) || "【待补核心信息】";
  }

  function channelLabel(channel) {
    const labels = { document: currentScenario().id === "gongwen" ? "机关文件" : "文档 / 报告", email: "电子邮件", meeting: "会议沟通", presentation: "演示汇报", web: "网站 / 公众号", social: "社交媒体", academic: "学术文本" };
    return labels[String(channel || "")] || "渠道变体";
  }

  function renderVariants() {
    const variants = Array.isArray(phase2State.variants) ? phase2State.variants : [];
    els.variantResults.replaceChildren();
    els.variantResults.classList.toggle("is-empty", !variants.length);
    if (!variants.length) {
      const p = document.createElement("p"); p.textContent = "渠道变体会作为独立文字资产呈现，并保留与当前母稿的关联。"; els.variantResults.append(p); return;
    }
    variants.forEach((variant) => {
      const article = document.createElement("article"); article.className = "variant-result-card";
      const head = document.createElement("div");
      const label = document.createElement("span"); label.textContent = channelLabel(variant.channel);
      const title = document.createElement("strong"); title.textContent = variant.title || channelLabel(variant.channel);
      head.append(label, title);
      const preview = document.createElement("p");
      const text = String(variant.content || "").replace(/\s+/g, " ").trim();
      preview.textContent = `${text.slice(0, 260)}${text.length > 260 ? "…" : ""}`;
      const foot = document.createElement("div");
      const meta = document.createElement("small"); meta.textContent = `${countChinese(text)} 字 · ${executionMode.execution(variant.execution)?.label || "生成来源未记录"} · 关联当前母稿`;
      const copy = document.createElement("button"); copy.type = "button"; copy.className = "mini-button"; copy.textContent = "复制全文";
      copy.addEventListener("click", () => copyPlainText(String(variant.content || ""), "渠道变体已复制"));
      foot.append(meta, copy); article.append(head, preview, foot); els.variantResults.append(article);
    });
  }

  async function copyPlainText(text, successMessage) {
    try { await navigator.clipboard.writeText(text); toast(successMessage, "success"); }
    catch (_) {
      const area = document.createElement("textarea"); area.value = text; area.style.position = "fixed"; area.style.opacity = "0";
      document.body.append(area); area.select(); document.execCommand("copy"); area.remove(); toast(successMessage, "success");
    }
  }

  async function searchKnowledge() {
    const query = els.knowledgeSearch.value.trim();
    if (!query) { els.knowledgeSearch.focus(); toast("请输入知识检索关键词", "warning"); return; }
    const projectId = requireActiveProject("检索项目材料");
    if (!projectId) return;
    const operationSerial = projectSwitchSerial;
    setButtonBusy(els.searchKnowledgeButton, true, "正在检索…");
    const kind = els.knowledgeKind.value;
    try {
      const pathForPage = (offset, limit) => {
        const params = kind
          ? new URLSearchParams({ query, kind, limit: String(limit), offset: String(offset) })
          : new URLSearchParams({ query, scope: "materials", limit: String(limit), offset: String(offset) });
        const resource = kind ? "materials" : "search";
        return `/api/v2/projects/${encodeURIComponent(projectId)}/${resource}?${params.toString()}`;
      };
      const first = await progressiveV2(pathForPage(0, PAGE_SIZE), {}, () => ({ items: localKnowledgeSearch(query) }));
      if (first.source === "local") {
        const items = Array.isArray(first.data?.items) ? first.data.items : [];
        renderKnowledgeResults(items, "local");
        return;
      }
      requireValidPage(first.data, "知识检索", 0, null);
      const items = [...first.data.items];
      const expectedTotal = first.data.total;
      let response = first.data;
      let pageCount = 1;
      while (response.has_more && pageCount < MAX_PAGE_COUNT) {
        const nextOffset = response.offset + response.count;
        response = await apiRequest(pathForPage(nextOffset, PAGE_SIZE));
        requireValidPage(response, "知识检索", nextOffset, expectedTotal);
        items.push(...response.items);
        pageCount += 1;
      }
      if (response.has_more) throw new Error("知识检索结果超过单次读取上限");
      if (projectOperationIsStale(projectId, operationSerial)) return;
      if (items.some((item) => !item || typeof item !== "object" || !String(item.id || "").trim())) throw new Error("知识检索返回了缺少 ID 的条目");
      renderKnowledgeResults(items, "server");
    } catch (error) {
      if (projectOperationIsStale(projectId, operationSerial, error)) return;
      renderKnowledgeResults([], "error", readError(error, "知识检索未完成"));
    } finally {
      if (!projectOperationIsStale(projectId, operationSerial)) setButtonBusy(els.searchKnowledgeButton, false);
    }
  }

  function localKnowledgeSearch(query) {
    const needle = query.toLocaleLowerCase("zh-CN");
    const references = (appState.styleReferences || []).filter((item) => [item.title, item.source_name, item.excerpt].join(" ").toLocaleLowerCase("zh-CN").includes(needle)).map((item) => ({
      id: item.id, kind: "article", title: item.title, source: item.source_name, excerpt: item.excerpt || "已选入当前任务的写法参考。",
    }));
    const materialItems = els.materials.value.split(/[。！？\n]+/).map((line) => line.trim()).filter((line) => line && line.toLocaleLowerCase("zh-CN").includes(needle)).slice(0, 8).map((line, index) => ({
      id: `local-fact-${index}`, kind: "fact", title: `当前材料命中 ${index + 1}`, source: "当前任务材料", excerpt: line,
    }));
    return [...references, ...materialItems].slice(0, 20);
  }

  function renderKnowledgeResults(items, source, errorMessage = "") {
    els.knowledgeResults.replaceChildren();
    els.knowledgeResults.classList.toggle("is-empty", !items.length);
    if (!items.length) {
      const p = document.createElement("p");
      p.textContent = errorMessage || (source === "local" ? "当前任务和已选文章中暂无匹配内容；可打开文章来源库继续导入或采集。" : "没有匹配的知识条目。 ");
      els.knowledgeResults.append(p); return;
    }
    items.forEach((item) => {
      const article = document.createElement("article"); article.className = "knowledge-result-item";
      const icon = document.createElement("i"); icon.textContent = item.kind === "fact" ? "实" : item.kind === "reference" ? "文" : "材";
      const copy = document.createElement("div");
      const title = document.createElement("strong"); title.textContent = String(item.title || item.label || "知识条目");
      const excerpt = document.createElement("p"); excerpt.textContent = String(item.preview || item.excerpt || item.summary || item.content || "").slice(0, 360);
      const meta = document.createElement("small"); meta.textContent = [item.source || item.source_name || item.kind, source === "server" ? "服务端知识库" : "本机预览"].filter(Boolean).join(" · ");
      copy.append(title, excerpt, meta); article.append(icon, copy); els.knowledgeResults.append(article);
    });
  }

  async function refreshKnowledgeStats() {
    els.knowledgeSelectedCount.textContent = String(currentScenario().id === "academic" ? phase2State.academic.records.length : (appState.styleReferences || []).length);
    const groups = extractFacts(els.materials.value);
    els.knowledgeFactCount.textContent = String(currentScenario().id === "academic" ? phase2State.academic.evidence.length : Object.values(groups).reduce((sum, values) => sum + values.length, 0));
    const projectId = String(phase2State.project_id || "");
    const operationSerial = projectSwitchSerial;
    const localProject = !projectId || isLocalProject(projectId);
    try {
      if (localProject) throw new Error("no-server-project");
      const result = await apiRequest(`/api/v2/projects/${encodeURIComponent(projectId)}/materials?limit=100&offset=0`);
      if (projectOperationIsStale(projectId, operationSerial)) return;
      requireValidPage(result, "材料统计", 0, null);
      els.knowledgeItemCount.textContent = String(result.total);
      setV2ServiceState("connected");
    } catch (error) {
      if (error?.name === "AbortError" || projectOperationIsStale(projectId, operationSerial)) return;
      els.knowledgeItemCount.textContent = !projectId ? "未选项目" : "待连接";
    }
  }

  async function loadWorkflowDefinitions(notify) {
    try {
      const params = new URLSearchParams({ limit: "100", offset: "0" });
      if (phase2State.brief.scenario_pack_id) params.set("scenario_pack_id", phase2State.brief.scenario_pack_id);
      const result = await apiRequest(`/api/v2/workflow-definitions?${params.toString()}`);
      setV2ServiceState("connected");
      const items = Array.isArray(result?.items) ? result.items : Array.isArray(result) ? result : [];
      renderServiceRecipes(items);
      if (notify) toast(items.length ? `已读取 ${items.length} 条服务端配方` : "服务端暂无额外配方", "success");
    } catch (_) {
      if (notify) toast("当前展示内置写作配方", "info");
    }
  }

  function renderServiceRecipes(items) {
    // Workflow definitions are not recipe IDs. Never pretend an unsupported
    // workflow card has been loaded as a known writing recipe.
    renderSceneRecipes();
  }

  function applyRecipe(recipeId) {
    const found = Object.entries(scenarioCatalog.recipes).flatMap(([packId, recipes]) => recipes.map((recipe) => ({ packId, recipe }))).find((item) => item.recipe.id === recipeId);
    if (!found) { toast("该配方未注册，请从场景目录选择", "warning"); return; }
    els.briefScenarioPack.value = found.packId;
    updateRecipeOptions(found.recipe.id, false);
    reconcileTaskContext("recipe");
    openSuiteView("projects", { focusId: "scenarioOverview" });
    persistPhase2State();
    toast(`已采用${scenarioCatalog.profiles[found.packId].name} · ${found.recipe.name}`, "success");
  }

  function appendRequirement(text) {
    const current = els.requirements.value.trim();
    if (!current.includes(text.trim())) els.requirements.value = [current, text.trim()].filter(Boolean).join("\n");
  }

  function updatePhase2Summaries() {
    if (!els.homeBriefPreview) return;
    updateProjectWorkflowStatus();
    const brief = currentBriefPayload();
    const completionFields = [
      ["主题", brief.title !== "未命名写作任务"],
      ["写作目的", Boolean(brief.goal)],
      ["阅读对象", Boolean(brief.audience)],
      ["内容形态", Boolean(brief.content_type)],
      ["首要渠道", Boolean(brief.channel)],
      ["写作配方", Boolean(brief.recipe_id)],
    ];
    const missingFields = completionFields.filter(([, completed]) => !completed).map(([label]) => label);
    const isComplete = missingFields.length === 0;
    els.briefCompletion.textContent = isComplete ? "核心要素已齐" : `待补 ${missingFields.length} 项`;
    els.briefCompletion.title = isComplete
      ? "主题、写作目的、阅读对象、内容形态、首要渠道和写作配方均已填写；日期、关键词和约束为选填项"
      : `待补：${missingFields.join("、")}；日期、关键词和约束为选填项`;
    els.briefCompletion.setAttribute("aria-label", els.briefCompletion.title);
    els.briefCompletion.classList.toggle("is-complete", isComplete);

    els.homeBriefPreview.replaceChildren();
    const title = document.createElement("strong"); title.textContent = brief.title;
    const description = document.createElement("p"); description.textContent = brief.goal || "补充写作目标后，砚章会将它贯穿标题、母稿、审校与渠道变体。";
    const tags = document.createElement("div");
    [contentTypeLabel(brief.content_type), brief.document_type, channelLabel(brief.channel), languageLabel(brief.target_language)].forEach((value) => {
      const tag = document.createElement("span"); tag.textContent = value; tags.append(tag);
    });
    els.homeBriefPreview.append(title, description, tags);

    const factGroups = extractFacts(els.materials.value);
    const factCount = Object.values(factGroups).reduce((sum, values) => sum + values.length, 0);
    els.knowledgeSelectedCount.textContent = String(currentScenario().id === "academic" ? phase2State.academic.records.length : (appState.styleReferences || []).length);
    els.knowledgeFactCount.textContent = String(currentScenario().id === "academic" ? phase2State.academic.evidence.length : factCount);
    els.variantSourceStatus.textContent = phase2State.document_stale
      ? "上一版草稿仅供对照 · 重新生成后可制作变体"
      : documentPlainText() ? `${countChinese(documentPlainText())} 字母稿已就绪` : "生成或输入母稿后，可一稿多用";
    const documentTitle = els.documentTitle.value.trim() || els.topic.value.trim();
    els.deliveryAssetTitle.textContent = documentTitle || "尚未形成母稿";
    els.deliveryAssetMeta.textContent = phase2State.document_stale
      ? "上一版草稿 · 按当前任务重新生成后再交付"
      : documentPlainText()
        ? `${els.documentType.value} · ${countChinese(documentPlainText())} 字 · ${phase2State.variants.length} 个渠道变体`
        : "完成任务简报并生成正文后，交付信息会在这里汇总。";
    updateReviewHub();
    updateSettingsOverview();
  }

  function contentTypeLabel(value) {
    const labels = { "official-document": "规范公文", "leadership-speech": "领导讲话", "research-report": "调研报告", "news-release": "新闻通稿", "academic-paper": "学术论文", "general-writing": "通用长文" };
    return labels[value] || "通用写作";
  }

  function languageLabel(value) { return value === "en" ? "英文" : value === "zh-en" ? "中英双语" : "中文"; }

  function currentReviewScore() {
    if (!appState.review) return null;
    const metrics = appState.factAudit?.metrics || {};
    const penalty = Math.min(35, (Number(metrics.contradicted_sentence_count) || 0) * 12 + (Number(metrics.unverified_sentence_count) || 0) * 4 + (Number(metrics.partial_sentence_count) || 0) * 3);
    return Math.max(0, Math.min(100, (Number(appState.review.score) || 0) - penalty));
  }

  function updateReviewHub() {
    const score = currentReviewScore();
    els.hubQualityScore.textContent = score === null ? "—" : String(score);
    els.hubScoreRing.style.setProperty("--hub-score", score || 0);
    els.reviewHubStatus.textContent = phase2State.document_stale ? "上一版草稿 · 待重生成" : score === null ? (documentPlainText() ? "母稿待审校" : "等待文稿") : score >= 90 ? "整体规范" : score >= 75 ? "建议优化" : "需要完善";
    els.reviewHubSummary.textContent = phase2State.document_stale ? "当前编辑区是上一版草稿；请按最新任务重新生成后，再运行综合审校。" : score === null ? (documentPlainText() ? "当前母稿已就绪，运行综合审校后查看问题分布。" : "生成或输入母稿后，可在这里启动完整审校。") : appState.review?.summary || "综合审校已完成，请结合证据逐项复核。";
    const dimensionIds = sceneReviewDimensionIds();
    els.hubFormatScore.textContent = score === null ? "待检" : reviewDimensionText(dimensionIds[0]);
    els.hubStructureScore.textContent = score === null ? "待检" : reviewDimensionText(dimensionIds[1]);
    const factMetrics = appState.factAudit?.metrics || {};
    els.hubFactScore.textContent = !appState.factAudit ? "待检" : Number(factMetrics.contradicted_sentence_count || 0) ? "疑似冲突" : `${Number(factMetrics.evidence_coverage_percent) || 0}% 有依据`;
    els.hubLanguageScore.textContent = score === null ? "待检" : reviewDimensionText(dimensionIds[3]);
    const coverage = phase2State.academic.coverage;
    const hasCoverage = coverage !== null && coverage !== "" && Number.isFinite(Number(coverage));
    els.hubCitationScore.textContent = currentScenario().id !== "academic" ? "见事实溯源" : hasCoverage ? `${Math.round(Number(coverage) * (Number(coverage) <= 1 ? 100 : 1))}%` : "待核验";
    renderAcademicIntegrity();
  }

  function sceneReviewDimensionIds() {
    return {
      gongwen: ["format", "logic", "evidence", "language"],
      workplace: ["clarity", "logic", "evidence", "format"],
      media: ["audience_tone", "logic", "evidence", "format"],
      academic: ["logic", "format", "evidence", "language"],
    }[currentScenario().id];
  }

  function reviewDimensionText(id) {
    const dimension = (appState.review?.dimensions || []).find((item) => item.dimension === id);
    return dimension?.score != null && String(dimension.score).trim() && Number.isFinite(Number(dimension.score)) ? `${dimension.score} 分` : "未单独评分";
  }

  function renderAcademicIntegrity() {
    if (!els.academicIntegrityStatus) return;
    const integrity = phase2State.academic.integrity;
    if (!integrity) {
      els.academicIntegrityResult.className = "academic-integrity-result";
      els.academicIntegrityStatus.textContent = "学术完整性待检";
      els.academicIntegritySummary.textContent = "导入文献并建立论断—证据链接后，综合审校会同步检查引用覆盖与稿件规则。";
      return;
    }
    if (integrity.error) {
      els.academicIntegrityResult.className = "academic-integrity-result is-warning";
      els.academicIntegrityStatus.textContent = "学术完整性检查未完成";
      els.academicIntegritySummary.textContent = String(integrity.error);
      return;
    }
    const audit = integrity.citation_audit || {};
    const coverage = Number.isFinite(Number(audit.coverage)) ? Math.round(Number(audit.coverage) * (Number(audit.coverage) <= 1 ? 100 : 1)) : null;
    const comments = Array.isArray(integrity.comments) ? integrity.comments : [];
    els.academicIntegrityResult.className = `academic-integrity-result ${integrity.passed ? "is-passed" : "is-warning"}`;
    els.academicIntegrityStatus.textContent = integrity.passed ? "学术完整性检查通过" : "学术完整性仍需复核";
    els.academicIntegritySummary.textContent = `${integrity.source === "local" ? "本地预览 · " : "服务端 · "}${coverage === null ? "引用覆盖待核" : `引用覆盖 ${coverage}%`} · ${comments.length} 条检查意见`;
  }

  async function runAcademicIntegrity(projectId) {
    if (!phase2State.academic.records.length) return null;
    const manuscript = [els.documentTitle.value.trim(), documentPlainText()].filter(Boolean).join("\n\n");
    if (manuscript.length > 1_000_000) throw new Error("学术稿件超过完整性审校的 100 万字符上限");
    const claims = academicClaims();
    const inputOperation = captureInputOperation(projectId);
    const selection = academicEvidenceSelection(1000);
    const links = academicCandidateLinks(claims, 1000);
    const journal = {
      name: "当前学术任务规则",
      citation_style: phase2State.academic.citation_style || "gb-t-7714",
      language: "zh-CN",
      required_sections: [],
      custom_rules: boundedTextList([phase2State.brief.constraints], 500, 50),
    };
    const result = await progressiveAcademicV2(`/api/v2/projects/${encodeURIComponent(projectId)}/academic/integrity`, { method: "POST", body: {
      manuscript,
      record_ids: selection.record_ids,
      evidence_ids: selection.evidence_ids,
      claims,
      links,
      journal,
    } }, () => ({ integrity_review: localAcademicIntegrity(claims) }));
    if (inputOperationIsStale(inputOperation)) return null;
    const review = result.source === "server" ? result.data?.integrity_review : result.data?.integrity_review || result.data;
    const audit = review?.citation_audit;
    const coverage = Number(audit?.coverage);
    if (!responseValidators.validateIntegrityReview(review, claims)) throw new Error("学术完整性服务返回的计数、覆盖率或通过状态不一致");
    const validatedLinks = validAcademicLinks(audit.links, claims);
    if (validatedLinks.length !== audit.links.length) throw new Error("学术完整性服务返回了无法追溯的引用链接");
    phase2State.academic.integrity = { ...review, source: result.source };
    phase2State.academic.coverage = coverage;
    renderAcademicIntegrity();
    persistPhase2State();
    return phase2State.academic.integrity;
  }

  function localAcademicIntegrity(claims) {
    const audit = localClaimAudit(claims);
    const comments = audit.comments.filter((comment) => comment.status !== "linked");
    return {
      citation_audit: audit,
      comments,
      passed: !comments.some((comment) => comment.severity === "error"),
    };
  }

  async function runProjectReview() {
    if (!documentPlainText()) { toast("请先生成或输入母稿正文", "warning"); return; }
    const projectId = requireActiveProject("运行综合审校");
    if (!projectId) return;
    const operationSerial = projectSwitchSerial;
    const inputOperation = captureInputOperation(projectId);
    setButtonBusy(els.hubRunReviewButton, true, "正在审校…");
    try {
      const master = await ensureMasterAsset();
      if (inputOperationIsStale(inputOperation)) return;
      if (master.source !== "server") {
        const completed = await runReview();
        if (projectOperationIsStale(projectId, operationSerial)) return;
        if (completed) toast("项目审校服务未写入；当前展示本地预览审校结果", "info");
        updatePhase2Summaries();
        return;
      }
      const requestedChecks = ["structure", "style", "facts", "citations", "terminology"];
      const expectedDimensions = ["evidence", "logic", "clarity", "audience_tone", "language", "format"];
      const response = await apiRequest(`/api/v2/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(master.id)}/review`, { method: "POST", body: {
        checks: requestedChecks,
        material_ids: serverMaterialIds(),
      } });
      if (inputOperationIsStale(inputOperation)) return;
      const review = response?.review;
      if (!responseValidators.validateProjectReviewEnvelope(response, {
        assetId: master.id,
        checks: requestedChecks,
        dimensions: expectedDimensions,
      })) throw new Error("审校服务返回的资产、维度、问题或指标不完整");
      let integrity = null;
      let integrityError = "";
      if (phase2State.academic.records.length) {
        try {
          integrity = await runAcademicIntegrity(projectId);
          if (inputOperationIsStale(inputOperation)) return;
          if (projectOperationIsStale(projectId, operationSerial)) return;
        } catch (error) {
          if (projectOperationIsStale(projectId, operationSerial, error)) return;
          integrityError = readError(error, "学术完整性检查未完成");
          phase2State.academic.integrity = { error: integrityError };
          renderAcademicIntegrity();
        }
      }
      const integrityIssues = (integrity?.comments || []).map((issue) => ({
        level: issue.severity || "warning",
        category: issue.category || "引用",
        message: issue.message || "",
        suggestion: issue.recommendation || "",
      }));
      appState.review = {
        score: Number(review.overall_score),
        dimensions: review.dimensions,
        summary: [(review.dimensions || []).map((item) => item.summary).filter(Boolean).slice(0, 2).join(" ") || (review.passed ? "六维审校通过。" : "六维审校发现待处理事项。"), integrity ? (integrity.passed ? "学术完整性检查通过。" : "学术引用仍需复核。") : ""].filter(Boolean).join(" "),
        metrics: {
          heading_count: [...els.documentEditor.querySelectorAll("h1,h2,h3,h4,h5,h6")].length,
          long_sentence_count: 0,
          ...(review.metrics || {}),
        },
        issues: [...(review.issues || []).map((issue) => ({
          level: issue.severity || "warning",
          category: issue.dimension || "表达",
          message: issue.message || "",
          suggestion: issue.suggestion || "",
        })), ...integrityIssues],
      };
      renderReview();
      updatePhase2Summaries();
      persistState();
      if (integrityError) toast(`基础审校已由项目服务完成；${integrityError}`, "warning");
      else if (integrity?.source === "local") toast("基础审校已由项目服务完成；学术完整性当前为本地预览结果", "info");
      else toast(integrity ? "综合审校及学术完整性检查已由项目服务完成" : "基础综合审校已由项目服务完成", "success");
    } catch (error) {
      if (projectOperationIsStale(projectId, operationSerial, error)) return;
      if (error?.name === "StaleDocumentError") { toast(error.message, "warning"); return; }
      toast(`项目审校失败：${readError(error, "请检查服务")}`, "error");
      if (phase2State.local_draft_mode !== false) {
        const completed = await runReview();
        if (projectOperationIsStale(projectId, operationSerial)) return;
        if (completed) toast("已按你开启的本地预览模式展示基础审校；服务端结果未写入", "info");
      }
      updatePhase2Summaries();
    } finally {
      if (!projectOperationIsStale(projectId, operationSerial)) setButtonBusy(els.hubRunReviewButton, false);
    }
  }

  async function exportProjectAsset(format = "docx") {
    if (!documentPlainText()) { toast("请先生成或输入正文", "warning"); return; }
    const projectId = requireActiveProject("导出项目资产");
    if (!projectId) return;
    const operationSerial = projectSwitchSerial;
    [els.deliveryWordButton, els.deliveryWordSecondaryButton].forEach((button) => setButtonBusy(button, true, "正在导出…"));
    try {
      const master = await ensureMasterAsset();
      if (master.source !== "server") {
        const exported = await exportDocx();
        if (projectOperationIsStale(projectId, operationSerial)) return;
        if (exported) toast("项目导出服务未写入；当前文件来自本地预览导出", "info");
        return;
      }
      const filename = `${safeFilename(els.documentTitle.value || "文字资产")}.${format === "text" ? "txt" : format}`;
      const response = await apiRequest(`/api/v2/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(master.id)}/export`, { method: "POST", body: {
        format,
        revision: phase2State.master_asset_revision || undefined,
        filename,
      } });
      const artifactId = String(response?.artifact_id || response?.artifact?.artifact_id || "");
      if (!artifactId) throw new Error("导出服务没有返回 artifact_id");
      const download = await fetch(`/api/v2/projects/${encodeURIComponent(projectId)}/exports/${encodeURIComponent(artifactId)}`, { headers: requestHeaders(), signal: projectRequestController.signal });
      if (!download.ok) throw await responseError(download);
      downloadBlob(await download.blob(), String(response?.filename || response?.artifact?.filename || filename));
      toast("项目资产已由服务端导出", "success");
    } catch (error) {
      if (projectOperationIsStale(projectId, operationSerial, error)) return;
      if (error?.name === "StaleDocumentError") { toast(error.message, "warning"); return; }
      toast(`项目资产导出失败：${readError(error, "请检查服务")}`, "error");
      if (phase2State.local_draft_mode !== false) {
        const exported = await exportDocx();
        if (projectOperationIsStale(projectId, operationSerial)) return;
        if (exported) toast("已按你开启的本地预览模式生成浏览器文件；服务端导出未完成", "info");
      }
    } finally {
      if (!projectOperationIsStale(projectId, operationSerial)) [els.deliveryWordButton, els.deliveryWordSecondaryButton].forEach((button) => setButtonBusy(button, false));
    }
  }

  function updateSettingsOverview() {
    const current = currentModelConnection();
    els.settingsEngineTitle.textContent = current.label;
    els.settingsEngineSummary.textContent = current.detail;
  }

  function clearPhase2Drafts() {
    if (!window.confirm("确定清理当前浏览器中的第二阶段简报、表达候选、渠道变体与学术草稿吗？现有公文母稿不受影响。")) return;
    projectSwitchSerial += 1;
    projectRequestController.abort(new DOMException("第二阶段本机草稿已清理", "AbortError"));
    projectRequestController = new AbortController();
    projectAssetsLoading = false;
    resetProjectActionButtons();
    localStorage.removeItem(PHASE2_KEY);
    phase2State = freshPhase2State();
    phase2State.view = "settings";
    applyPhase2StateToUI();
    toast("第二阶段本机草稿已清理", "success");
  }

  function clearAllLocalData() {
    if (!window.confirm("这会清除本浏览器中的母稿、材料、历史快照、第二阶段项目草稿与模型设置。是否继续？")) return;
    if (!window.confirm("请再次确认：清除后，本机浏览器数据与当前会话访问令牌将立即移除。")) return;
    [STORAGE_KEY, SETTINGS_KEY, HISTORY_KEY, PHASE2_KEY].forEach((key) => localStorage.removeItem(key));
    clearAccessToken();
    sessionApiKey = "";
    settings = { mode: "demo", providerName: "openai", baseUrl: "", modelName: "" };
    appState = freshState();
    phase2State = freshPhase2State();
    projectAssetsLoading = false;
    projectSwitchSerial += 1;
    projectRequestController.abort(new DOMException("本机会话已清除", "AbortError"));
    projectRequestController = new AbortController();
    applyStateToUI();
    els.documentTitle.value = "";
    els.documentEditor.replaceChildren();
    els.generationHero.classList.remove("is-hidden");
    els.documentWorkspace.classList.add("is-hidden");
    applyPhase2StateToUI();
    syncSettingsUI();
    toast("本机浏览器数据与会话令牌已清除", "success");
    if (accessTokenRequired) showAccessGate("本机会话已清除，请重新输入访问令牌。");
  }

  const academicOperationSerials = new Map();

  function academicOperationFields(action) {
    const fields = action === "import"
      ? ["academicImportFormat", "academicImportContent"]
      : action === "evidence"
        ? ["academicEvidenceRecord", "academicEvidenceQuery", "academicEvidenceText"]
        : [];
    return JSON.stringify(fields.map((field) => String(els[field]?.value || "")));
  }

  function captureAcademicOperation(projectId, action) {
    const requestSerial = (academicOperationSerials.get(action) || 0) + 1;
    academicOperationSerials.set(action, requestSerial);
    return { input: captureInputOperation(projectId), action, requestSerial, fields: academicOperationFields(action) };
  }

  function academicOperationIsStale(operation, error = null) {
    return academicOperationSerials.get(operation.action) !== operation.requestSerial
      || operation.fields !== academicOperationFields(operation.action)
      || inputOperationIsStale(operation.input, error);
  }

  function finishAcademicOperation(operation, button) {
    if (academicOperationSerials.get(operation.action) === operation.requestSerial
      && !projectOperationIsStale(operation.input.projectId, operation.input.projectSerial)) setButtonBusy(button, false);
  }

  async function importAcademicRecords() {
    const content = els.academicImportContent.value.trim();
    if (!content) { els.academicImportContent.focus(); toast("请粘贴参考文献记录", "warning"); return; }
    const format = els.academicImportFormat.value;
    const projectId = requireActiveProject("导入参考文献");
    if (!projectId) return;
    const inputOperation = captureAcademicOperation(projectId, "import");
    setButtonBusy(els.academicImportButton, true, "正在解析…");
    try {
      const localRecords = normalizeAcademicRecords(parseAcademicRecordsLocally(format, content));
      if (!localRecords.length) throw new Error("没有识别到完整文献记录，请检查所选格式和题名字段");
      const prospectiveRecords = new Map(phase2State.academic.records.map((record) => [bibliographicIdentity(record), record]));
      localRecords.forEach((record) => prospectiveRecords.set(bibliographicIdentity(record), record));
      if (prospectiveRecords.size > MAX_ACADEMIC_RECORDS) throw new Error(`单个项目最多载入 ${MAX_ACADEMIC_RECORDS} 篇参考文献，请拆分为多个项目`);
      const result = await progressiveV2(`/api/v2/projects/${encodeURIComponent(projectId)}/academic/literature/import`, { method: "POST", body: { format, content, tags: [] } }, () => ({ records: localRecords }));
      if (academicOperationIsStale(inputOperation)) return;
      const rawRecords = result.data?.records || result.data?.items || result.data;
      if (result.source === "server" && (!Array.isArray(rawRecords) || rawRecords.some((record) => !String(record?.id || "").trim() || !String(record?.title || "").trim()))) throw new Error("文献服务没有返回可追溯的记录 ID 与题名");
      const records = normalizeAcademicRecords(rawRecords).map((record) => ({ ...record, _server_synced: result.source === "server" }));
      if (!records.length) throw new Error("没有识别到完整文献记录，请检查所选格式和题名字段");
      const byIdentity = new Map(phase2State.academic.records.map((record) => [bibliographicIdentity(record), record]));
      records.forEach((record) => byIdentity.set(bibliographicIdentity(record), record));
      if (byIdentity.size > MAX_ACADEMIC_RECORDS) throw new Error(`项目参考文献超过 ${MAX_ACADEMIC_RECORDS} 篇上限`);
      phase2State.academic.records = [...byIdentity.values()];
      phase2State.academic.matrix = [];
      phase2State.academic.matrix_meta = null;
      phase2State.academic.citations = [];
      phase2State.academic.outline = null;
      phase2State.academic.claim_links = [];
      phase2State.academic.claim_comments = [];
      phase2State.academic.coverage = null;
      phase2State.academic.integrity = null;
      phase2State.academic.import_content = "";
      els.academicImportContent.value = "";
      renderAcademicRecords(); renderAcademicMatrix(); renderAcademicClaimLinks(); renderAcademicCitations(); renderAcademicOutline(); renderAcademicIntegrity();
      persistPhase2State();
      toast(result.source === "server" ? `已将 ${records.length} 篇参考文献写入当前项目` : `文献服务写入失败；已按本地预览模式解析 ${records.length} 篇`, result.source === "server" ? "success" : "info");
    } catch (error) {
      if (academicOperationIsStale(inputOperation, error)) return;
      toast(readError(error, "参考文献导入未完成"), "error");
    } finally {
      finishAcademicOperation(inputOperation, els.academicImportButton);
    }
  }

  function parseAcademicRecordsLocally(format, content) {
    if (format === "csl-json") return parseCslJson(content);
    if (format === "ris") return parseRis(content);
    return parseBibTex(content);
  }

  function parseBibTex(content) {
    const records = [];
    const starts = [...content.matchAll(/@([a-zA-Z]+)\s*\{\s*([^,\s]+)\s*,/g)];
    starts.forEach((match, index) => {
      const bodyStart = (match.index || 0) + match[0].length;
      const bodyEnd = index + 1 < starts.length ? starts[index + 1].index : content.length;
      const body = content.slice(bodyStart, bodyEnd).replace(/\}\s*$/, "");
      const fields = {};
      const fieldPattern = /([a-zA-Z][\w-]*)\s*=\s*(?:\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}|"([^"]*)"|([^,\n]+))/g;
      for (const field of body.matchAll(fieldPattern)) fields[field[1].toLowerCase()] = String(field[2] ?? field[3] ?? field[4] ?? "").replace(/[{}]/g, "").trim();
      if (!fields.title) return;
      records.push({
        id: match[2], source_key: match[2], type: match[1].toLowerCase(), title: fields.title,
        authors: parseAuthorNames(fields.author || ""), editors: parseAuthorNames(fields.editor || ""),
        issued_year: yearFromValue(fields.year || fields.date), container_title: fields.journal || fields.booktitle || "",
        publisher: fields.publisher || "", publisher_place: fields.address || "", volume: fields.volume || "",
        issue: fields.number || fields.issue || "", pages: fields.pages || "", edition: fields.edition || "",
        doi: fields.doi || "", url: fields.url || "", abstract: fields.abstract || "",
        keywords: String(fields.keywords || "").split(/[;,，；]+/).map((item) => item.trim()).filter(Boolean),
        language: fields.language || "", import_source: "bibtex",
      });
    });
    return records;
  }

  function parseRis(content) {
    return content.split(/\nER\s{0,2}-\s*[^\n]*\n?/i).map((block, blockIndex) => {
      const fields = {};
      block.split(/\r?\n/).forEach((line) => {
        const match = line.match(/^([A-Z0-9]{2})\s{0,2}-\s?(.*)$/);
        if (!match) return;
        if (!fields[match[1]]) fields[match[1]] = [];
        fields[match[1]].push(match[2].trim());
      });
      const title = fields.TI?.[0] || fields.T1?.[0] || "";
      if (!title) return null;
      return {
        id: fields.ID?.[0] || `ris-${blockIndex + 1}`, source_key: fields.ID?.[0] || "", type: fields.TY?.[0] || "article-journal", title,
        authors: (fields.AU || fields.A1 || []).flatMap(parseAuthorNames), editors: (fields.ED || []).flatMap(parseAuthorNames),
        issued_year: yearFromValue(fields.PY?.[0] || fields.Y1?.[0]), container_title: fields.JO?.[0] || fields.JF?.[0] || fields.T2?.[0] || "",
        publisher: fields.PB?.[0] || "", publisher_place: fields.CY?.[0] || "", volume: fields.VL?.[0] || "",
        issue: fields.IS?.[0] || "", pages: [fields.SP?.[0], fields.EP?.[0]].filter(Boolean).join("-"), edition: fields.ET?.[0] || "",
        doi: fields.DO?.[0] || "", url: fields.UR?.[0] || "", abstract: fields.AB?.join(" ") || "",
        keywords: fields.KW || [], language: fields.LA?.[0] || "", import_source: "ris",
      };
    }).filter(Boolean);
  }

  function parseCslJson(content) {
    const parsed = JSON.parse(content);
    const items = Array.isArray(parsed) ? parsed : Array.isArray(parsed?.items) ? parsed.items : [parsed];
    return items.filter((item) => item && typeof item === "object" && item.title).map((item, index) => ({
      ...item,
      id: String(item.id || `csl-${index + 1}`),
      source_key: String(item.id || ""),
      authors: normalizeAcademicAuthors(item.author || item.authors || []),
      editors: normalizeAcademicAuthors(item.editor || item.editors || []),
      issued_year: Number(item.issued_year || item.issued?.["date-parts"]?.[0]?.[0]) || null,
      issued_month: Number(item.issued_month || item.issued?.["date-parts"]?.[0]?.[1]) || null,
      issued_day: Number(item.issued_day || item.issued?.["date-parts"]?.[0]?.[2]) || null,
      container_title: item.container_title || item["container-title"] || "",
      publisher_place: item.publisher_place || item["publisher-place"] || "",
      abstract: item.abstract || "", keywords: Array.isArray(item.keyword) ? item.keyword : String(item.keyword || "").split(/[;,，；]+/).filter(Boolean),
      import_source: "csl-json",
    }));
  }

  function normalizeAcademicRecords(raw) {
    if (!Array.isArray(raw)) return [];
    return raw.map((record, index) => {
      if (!record || typeof record !== "object") return null;
      const title = String(record.title || "").trim();
      if (!title) return null;
      const authors = normalizeAcademicAuthors(record.authors || record.author || []);
      const issuedYear = Number(record.issued_year || record.year || record.issued?.["date-parts"]?.[0]?.[0]) || null;
      const sourceHash = String(record.source_hash || simpleHash([title, issuedYear, record.doi, record.url, JSON.stringify(authors)].join("|")));
      return {
        id: String(record.id || record.source_key || `ref-${sourceHash}-${index + 1}`),
        type: String(record.type || "article-journal"), title, authors,
        editors: normalizeAcademicAuthors(record.editors || record.editor || []),
        issued_year: issuedYear,
        issued_month: Number(record.issued_month) || null,
        issued_day: Number(record.issued_day) || null,
        container_title: String(record.container_title || record["container-title"] || ""),
        publisher: String(record.publisher || ""), publisher_place: String(record.publisher_place || record["publisher-place"] || ""),
        volume: String(record.volume || ""), issue: String(record.issue || ""), pages: String(record.pages || record.page || ""),
        edition: String(record.edition || ""), doi: String(record.doi || record.DOI || ""), url: String(record.url || record.URL || ""),
        abstract: String(record.abstract || ""), keywords: Array.isArray(record.keywords) ? record.keywords.map(String) : String(record.keyword || "").split(/[;,，；]+/).map((item) => item.trim()).filter(Boolean),
        language: String(record.language || ""), import_source: String(record.import_source || "manual"),
        source_key: String(record.source_key || record.id || ""), source_hash: sourceHash,
        metadata_verified: Boolean(record.metadata_verified), imported_at: String(record.imported_at || new Date().toISOString()),
      };
    }).filter(Boolean);
  }

  function normalizeAcademicAuthors(value) {
    if (typeof value === "string") return parseAuthorNames(value);
    if (!Array.isArray(value)) return [];
    return value.map((author, index) => {
      if (typeof author === "string") return parseAuthorNames(author)[0];
      if (!author || typeof author !== "object") return null;
      return { family: String(author.family || ""), given: String(author.given || ""), literal: String(author.literal || ""), sequence: String(author.sequence || (index === 0 ? "first" : "additional")) };
    }).filter(Boolean);
  }

  function parseAuthorNames(value) {
    return String(value || "").split(/\s+and\s+|;|；/i).map((name, index) => {
      const clean = name.trim(); if (!clean) return null;
      if (clean.includes(",")) {
        const [family, ...given] = clean.split(",");
        return { family: family.trim(), given: given.join(",").trim(), literal: "", sequence: index === 0 ? "first" : "additional" };
      }
      const parts = clean.split(/\s+/);
      if (parts.length === 1 || /[\u4e00-\u9fa5]/.test(clean)) return { family: "", given: "", literal: clean, sequence: index === 0 ? "first" : "additional" };
      return { family: parts.pop(), given: parts.join(" "), literal: "", sequence: index === 0 ? "first" : "additional" };
    }).filter(Boolean);
  }

  function yearFromValue(value) { const match = String(value || "").match(/(?:19|20)\d{2}/); return match ? Number(match[0]) : null; }
  function simpleHash(value) { let hash = 2166136261; for (const char of String(value || "")) { hash ^= char.charCodeAt(0); hash = Math.imul(hash, 16777619); } return (hash >>> 0).toString(36); }
  function bibliographicIdentity(record) { return String(record.doi || record.url || record.source_hash || `${record.title}|${record.issued_year || ""}`).toLocaleLowerCase("zh-CN"); }

  function renderAcademicRecords() {
    const records = phase2State.academic.records;
    const serverTotal = Number(phase2State.academic.restore_totals?.records);
    els.academicReferenceCount.textContent = Number.isInteger(serverTotal) && serverTotal > records.length ? `${records.length}/${serverTotal} 篇` : `${records.length} 篇`;
    els.academicRecords.replaceChildren();
    els.academicRecords.classList.toggle("is-empty", !records.length);
    if (!records.length) {
      const p = document.createElement("p"); p.textContent = "尚未导入参考文献"; els.academicRecords.append(p);
    } else records.forEach((record, index) => {
      const article = document.createElement("article"); article.className = "academic-record";
      const number = document.createElement("i"); number.textContent = `R-${String(index + 1).padStart(2, "0")}`;
      const copy = document.createElement("div");
      const title = document.createElement("strong"); title.textContent = record.title;
      const meta = document.createElement("small"); meta.textContent = [academicAuthorLabel(record.authors), record.issued_year, record.container_title].filter(Boolean).join(" · ") || "元数据待补充";
      copy.append(title, meta);
      const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "×"; remove.setAttribute("aria-label", `移除${record.title}`);
      remove.addEventListener("click", () => removeAcademicRecord(record.id));
      article.append(number, copy, remove); els.academicRecords.append(article);
    });
    const current = phase2State.academic.evidence_record_id;
    els.academicEvidenceRecord.replaceChildren();
    if (!records.length) els.academicEvidenceRecord.append(makeOption("", "先导入文献"));
    else {
      els.academicEvidenceRecord.append(makeOption("", "选择来源文献"), ...records.map((record, index) => makeOption(record.id, `R-${String(index + 1).padStart(2, "0")}｜${record.title.slice(0, 34)}`)));
      els.academicEvidenceRecord.value = records.some((record) => record.id === current) ? current : "";
    }
    updatePhase2Summaries();
  }

  function academicAuthorLabel(authors) {
    const names = (authors || []).map((author) => author.literal || [author.given, author.family].filter(Boolean).join(" ")).filter(Boolean);
    if (!names.length) return "";
    return names.length > 3 ? `${names.slice(0, 3).join("、")} 等` : names.join("、");
  }

  function removeAcademicRecord(recordId) {
    phase2State.academic.records = phase2State.academic.records.filter((record) => record.id !== recordId);
    phase2State.academic.evidence = phase2State.academic.evidence.filter((item) => item.record_id !== recordId);
    phase2State.academic.claim_links = [];
    phase2State.academic.claim_comments = [];
    phase2State.academic.matrix = [];
    phase2State.academic.matrix_meta = null;
    phase2State.academic.coverage = null;
    phase2State.academic.citations = [];
    phase2State.academic.outline = null;
    phase2State.academic.integrity = null;
    renderAcademicRecords(); renderAcademicMatrix(); renderAcademicEvidence(); renderAcademicClaimLinks(); renderAcademicCitations(); renderAcademicOutline(); renderAcademicIntegrity();
    persistPhase2State();
  }

  async function generateAcademicMatrix() {
    const records = phase2State.academic.records;
    if (!records.length) { toast("请先导入参考文献", "warning"); return; }
    const projectId = requireActiveProject("生成文献矩阵");
    if (!projectId) return;
    const inputOperation = captureAcademicOperation(projectId, "matrix");
    setButtonBusy(els.academicMatrixButton, true, "正在整理…");
    try {
      const selection = academicEvidenceSelection(MAX_ACADEMIC_RECORDS);
      const result = await progressiveAcademicV2(`/api/v2/projects/${encodeURIComponent(projectId)}/academic/matrix`, { method: "POST", body: {
        record_ids: selection.record_ids,
        evidence_ids: selection.evidence_ids,
        query: phase2State.academic.title || phase2State.academic.goal || "",
      } }, () => localAcademicMatrix(records));
      if (academicOperationIsStale(inputOperation)) return;
      const matrix = result.data?.matrix || result.data || {};
      const rows = Array.isArray(matrix.rows) ? matrix.rows : Array.isArray(matrix.items) ? matrix.items : Array.isArray(matrix) ? matrix : [];
      if (result.source === "server" && !isCanonicalAcademicMatrix(matrix, selection)) throw new Error("文献矩阵服务没有返回可追溯的完整矩阵");
      if (!rows.length) throw new Error("文献矩阵服务没有返回可用行");
      phase2State.academic.matrix = rows;
      phase2State.academic.matrix_meta = { id: matrix.id || "", query: matrix.query || phase2State.academic.title, themes: Array.isArray(matrix.themes) ? matrix.themes : [] };
      renderAcademicMatrix(); persistPhase2State(); toast(result.source === "server" ? "文献矩阵已保存到当前项目" : "矩阵服务执行失败；已按本地预览模式生成", result.source === "server" ? "success" : "info");
    } catch (error) { if (!academicOperationIsStale(inputOperation, error)) toast(readError(error, "文献矩阵生成未完成"), "error"); }
    finally { finishAcademicOperation(inputOperation, els.academicMatrixButton); }
  }

  function localAcademicMatrix(records) {
    const evidence = phase2State.academic.evidence;
    return { id: `matrix-${Date.now()}`, query: phase2State.academic.title, record_ids: records.map((record) => record.id), themes: uniqueAcademicThemes(records), rows: records.map((record) => {
      const sentences = record.abstract.split(/[。！？.!?]+/).map((item) => item.trim()).filter(Boolean);
      return {
        record_id: record.id, citation_label: citationLabel(record), research_object: sentences.find((item) => /研究|分析|考察|探讨|对象|样本/.test(item)) || "",
        methods: sentences.filter((item) => /方法|采用|基于|样本|模型|访谈|调查/.test(item)).slice(0, 2),
        findings: sentences.filter((item) => /发现|结果|表明|认为|结论/.test(item)).slice(0, 2),
        limitations: sentences.filter((item) => /局限|不足|限制/.test(item)).slice(0, 1),
        themes: (record.keywords || []).slice(0, 5), evidence_ids: evidence.filter((item) => item.record_id === record.id).map((item) => item.id),
      };
    }) };
  }

  function isCanonicalAcademicMatrix(matrix, selection) {
    return Boolean(responseValidators?.validateAcademicMatrix?.(matrix, {
      recordIds: selection.record_ids,
      evidenceIds: selection.evidence_ids,
    }));
  }

  function academicEvidenceSelection(maxRecords = MAX_ACADEMIC_RECORDS) {
    const knownIds = phase2State.academic.records.map((record) => String(record.id)).filter(Boolean);
    const knownSet = new Set(knownIds);
    const evidenceRecordIds = phase2State.academic.evidence.map((item) => String(item.record_id)).filter((id) => knownSet.has(id));
    const recordIds = [...new Set([...evidenceRecordIds, ...knownIds])].slice(0, maxRecords);
    const allowedRecords = new Set(recordIds);
    const evidenceIds = phase2State.academic.evidence
      .filter((item) => allowedRecords.has(String(item.record_id)))
      .map((item) => String(item.id))
      .filter(Boolean)
      .slice(0, MAX_ACADEMIC_EVIDENCE);
    return { record_ids: recordIds, evidence_ids: evidenceIds };
  }

  function uniqueAcademicThemes(records) { return [...new Set(records.flatMap((record) => record.keywords || []).map(String).filter(Boolean))].slice(0, 12); }
  function citationLabel(record) { return [academicAuthorLabel(record.authors) || record.title.slice(0, 12), record.issued_year].filter(Boolean).join("，"); }

  function renderAcademicMatrix() {
    const rows = phase2State.academic.matrix || [];
    els.academicMatrixBody.replaceChildren();
    if (!rows.length) {
      const tr = document.createElement("tr"); const td = document.createElement("td"); td.colSpan = 4; td.textContent = "导入参考文献后生成矩阵"; tr.append(td); els.academicMatrixBody.append(tr); return;
    }
    rows.forEach((row) => {
      const record = phase2State.academic.records.find((item) => item.id === row.record_id);
      const tr = document.createElement("tr");
      [row.citation_label || (record ? citationLabel(record) : row.record_id), joinAcademicValue([row.research_object, row.methods]), joinAcademicValue(row.findings), joinAcademicValue([row.limitations, row.themes])].forEach((value) => {
        const td = document.createElement("td"); td.textContent = value || "待从文献原文补充"; tr.append(td);
      });
      els.academicMatrixBody.append(tr);
    });
  }

  function joinAcademicValue(value) {
    const flattened = (Array.isArray(value) ? value.flat(2) : [value]).filter(Boolean).map(String);
    return [...new Set(flattened)].join("；");
  }

  async function extractAcademicEvidence() {
    const recordId = els.academicEvidenceRecord.value;
    const text = els.academicEvidenceText.value.trim();
    if (!recordId) { els.academicEvidenceRecord.focus(); toast("请选择证据对应的真实文献", "warning"); return; }
    if (!text) { els.academicEvidenceText.focus(); toast("请粘贴可核验的原文片段", "warning"); return; }
    const record = phase2State.academic.records.find((item) => item.id === recordId);
    if (!record) { toast("所选文献记录已变化，请重新选择", "warning"); renderAcademicRecords(); return; }
    const projectId = requireActiveProject("提取文献证据");
    if (!projectId) return;
    const inputOperation = captureAcademicOperation(projectId, "evidence");
    setButtonBusy(els.academicExtractEvidenceButton, true, "正在提取…");
    try {
      const request = { record_id: recordId, text, query: els.academicEvidenceQuery.value.trim(), max_snippets: 8 };
      const localFallback = () => ({ snippets: localEvidenceSnippets(record, text, request.query, 8) });
      const result = record._server_synced === false
        ? { data: localFallback(), source: "local" }
        : await progressiveV2(`/api/v2/projects/${encodeURIComponent(projectId)}/academic/evidence/extract`, { method: "POST", body: {
        record_id: recordId, text, query: els.academicEvidenceQuery.value.trim(), max_snippets: 8,
      } }, localFallback);
      if (academicOperationIsStale(inputOperation)) return;
      const rawSnippets = result.data?.snippets || result.data?.items || result.data;
      if (result.source === "server" && (!Array.isArray(rawSnippets) || rawSnippets.some((snippet) => !String(snippet?.id || "").trim()
        || String(snippet?.record_id || "") !== recordId || !String(snippet?.record_source_hash || "").trim()
        || !String(snippet?.text || "").trim()))) throw new Error("证据服务没有返回可追溯的原文位置");
      const snippets = normalizeEvidenceSnippets(rawSnippets, record).map((snippet) => ({ ...snippet, _server_synced: result.source === "server" }));
      if (!snippets.length) throw new Error("没有提取到与检索焦点匹配的原文句段，请调整焦点或补充文本");
      const byId = new Map(phase2State.academic.evidence.map((item) => [item.id, item]));
      snippets.forEach((snippet) => byId.set(snippet.id, snippet));
      phase2State.academic.evidence = [...byId.values()].slice(0, MAX_ACADEMIC_EVIDENCE);
      phase2State.academic.matrix = [];
      phase2State.academic.outline = null;
      phase2State.academic.claim_links = [];
      phase2State.academic.claim_comments = [];
      phase2State.academic.coverage = null;
      phase2State.academic.integrity = null;
      renderAcademicEvidence(); renderAcademicMatrix(); renderAcademicClaimLinks(); renderAcademicOutline(); renderAcademicIntegrity(); persistPhase2State(); toast(result.source === "server" ? `已写入 ${snippets.length} 条证据片段` : `证据服务执行失败；已按本地预览模式提取 ${snippets.length} 条`, result.source === "server" ? "success" : "info");
    } catch (error) { if (!academicOperationIsStale(inputOperation, error)) toast(readError(error, "证据提取未完成"), "error"); }
    finally { finishAcademicOperation(inputOperation, els.academicExtractEvidenceButton); }
  }

  function localEvidenceSnippets(record, text, query, maxSnippets) {
    const terms = significantTerms(query);
    const segments = [...text.matchAll(/[^。！？\n]+[。！？]?/g)].map((match) => ({ text: match[0].trim(), start: match.index || 0 })).filter((item) => item.text.length >= 8);
    const selected = (terms.length ? segments.filter((item) => terms.some((term) => item.text.includes(term))) : segments).slice(0, maxSnippets);
    return selected.map((item, index) => ({
      id: `ev-${simpleHash(`${record.id}|${item.start}|${item.text}`)}`,
      record_id: record.id, record_source_hash: record.source_hash, text: item.text, kind: "quotation",
      section: "用户粘贴片段", page_start: null, page_end: null, paragraph_index: index + 1,
      char_start: item.start, char_end: item.start + item.text.length,
      content_hash: simpleHash(item.text), extraction_method: "local-exact-extract",
    }));
  }

  function significantTerms(value) {
    const text = String(value || "").replace(/[的了是在和与及或对中为将把等]/g, " ");
    const words = text.match(/[A-Za-z0-9_-]{2,}|[\u4e00-\u9fa5]{2,}/g) || [];
    return [...new Set(words.flatMap((word) => /[\u4e00-\u9fa5]{4,}/.test(word) ? [word, ...Array.from({ length: word.length - 1 }, (_, index) => word.slice(index, index + 2))] : [word]))].slice(0, 40);
  }

  function normalizeEvidenceSnippets(raw, record) {
    if (!Array.isArray(raw)) return [];
    return raw.map((item, index) => {
      if (!item || typeof item !== "object" || !String(item.text || "").trim()) return null;
      const text = String(item.text).trim();
      return {
        id: String(item.id || `ev-${simpleHash(`${record.id}|${text}|${index}`)}`), record_id: record.id,
        record_source_hash: String(item.record_source_hash || record.source_hash), text,
        kind: String(item.kind || "quotation"), section: String(item.section || ""),
        page_start: item.page_start ?? null, page_end: item.page_end ?? null,
        paragraph_index: item.paragraph_index !== null && item.paragraph_index !== undefined && Number(item.paragraph_index) >= 1 ? Number(item.paragraph_index) : null,
        char_start: Number.isFinite(Number(item.char_start)) ? Number(item.char_start) : null,
        char_end: Number.isFinite(Number(item.char_end)) ? Number(item.char_end) : null,
        content_hash: String(item.content_hash || simpleHash(text)), extraction_method: String(item.extraction_method || "service"),
      };
    }).filter(Boolean);
  }

  function renderAcademicEvidence() {
    const snippets = phase2State.academic.evidence || [];
    els.academicEvidenceSnippets.replaceChildren();
    els.academicEvidenceSnippets.classList.toggle("is-empty", !snippets.length);
    if (!snippets.length) {
      const p = document.createElement("p"); p.textContent = "证据片段将保留真实文献 ID 与文本位置"; els.academicEvidenceSnippets.append(p); return;
    }
    snippets.slice(-20).reverse().forEach((snippet) => {
      const record = phase2State.academic.records.find((item) => item.id === snippet.record_id);
      const article = document.createElement("article"); article.className = "evidence-snippet";
      const top = document.createElement("div");
      const source = document.createElement("b"); source.textContent = record ? citationLabel(record) : snippet.record_id;
      const location = document.createElement("span"); location.textContent = evidenceLocation(snippet);
      top.append(source, location);
      const quote = document.createElement("p"); quote.textContent = snippet.text;
      const foot = document.createElement("small"); foot.textContent = `证据 ID：${snippet.id}`;
      article.append(top, quote, foot); els.academicEvidenceSnippets.append(article);
    });
  }

  function evidenceLocation(snippet) {
    if (snippet.page_start) return snippet.page_end && snippet.page_end !== snippet.page_start ? `第 ${snippet.page_start}—${snippet.page_end} 页` : `第 ${snippet.page_start} 页`;
    if (Number.isFinite(Number(snippet.paragraph_index)) && Number(snippet.paragraph_index) >= 1) return `第 ${Number(snippet.paragraph_index)} 段`;
    return snippet.section || "原文片段";
  }

  async function verifyAcademicClaims() {
    const claims = academicClaims();
    if (!claims.length) { els.academicClaims.focus(); toast("请逐行填写需要核验的核心论断", "warning"); return; }
    if (!phase2State.academic.records.length || !phase2State.academic.evidence.length) { toast("请先导入文献并提取原文证据", "warning"); return; }
    const projectId = requireActiveProject("核验学术引用");
    if (!projectId) return;
    const inputOperation = captureAcademicOperation(projectId, "claims");
    setButtonBusy(els.academicVerifyClaimsButton, true, "正在核验…");
    try {
      const selection = academicEvidenceSelection(MAX_ACADEMIC_RECORDS);
      const allowedRecords = new Set(selection.record_ids);
      const allowedEvidence = new Set(selection.evidence_ids);
      const existingLinks = academicCandidateLinks(claims, MAX_ACADEMIC_RECORDS)
        .filter((link) => allowedRecords.has(link.record_id) && allowedEvidence.has(link.evidence_id));
      const result = await progressiveAcademicV2(`/api/v2/projects/${encodeURIComponent(projectId)}/academic/citations/verify`, { method: "POST", body: {
        record_ids: selection.record_ids,
        evidence_ids: selection.evidence_ids,
        claims,
        links: existingLinks,
      } }, () => localClaimAudit(claims));
      if (academicOperationIsStale(inputOperation)) return;
      const audit = result.source === "server" ? result.data?.citation_audit : result.data?.citation_audit || result.data?.audit || result.data || {};
      if (!isCanonicalCitationAudit(audit, claims)) throw new Error("引用核验服务返回的计数、覆盖率或链接状态不一致");
      const validatedLinks = validAcademicLinks(audit.links, claims);
      if (result.source === "server" && validatedLinks.length !== audit.links.length) throw new Error("引用核验服务返回了无法追溯的链接");
      phase2State.academic.claims = claims;
      phase2State.academic.claims_dirty = result.source !== "server";
      phase2State.academic.claim_links = validatedLinks;
      phase2State.academic.claim_comments = normalizeClaimComments(audit.comments, claims, phase2State.academic.claim_links);
      phase2State.academic.coverage = Number(audit.coverage);
      renderAcademicClaimLinks(); persistPhase2State(); toast(result.source === "server" ? "论断—证据核验已写入当前项目" : "引用核验服务执行失败；已按本地预览模式完成候选匹配", result.source === "server" ? "success" : "info");
    } catch (error) { if (!academicOperationIsStale(inputOperation, error)) toast(readError(error, "论断证据核验未完成"), "error"); }
    finally { finishAcademicOperation(inputOperation, els.academicVerifyClaimsButton); }
  }

  function academicClaims() {
    const saved = Array.isArray(phase2State.academic.claims) ? phase2State.academic.claims : [];
    const savedByText = new Map(saved.map((claim) => [String(claim?.text || "").trim(), claim]));
    return els.academicClaims.value.split(/\r?\n/).map((text) => text.trim()).filter(Boolean).slice(0, 500).map((text, index) => {
      const existing = savedByText.get(text);
      return existing?.id ? { ...existing, id: String(existing.id), text } : { id: `claim-${simpleHash(`${index}|${text}`)}`, text };
    });
  }

  function localClaimAudit(claims) {
    const links = [];
    const comments = [];
    claims.forEach((claim) => {
      const scored = phase2State.academic.evidence.map((snippet) => ({ snippet, score: lexicalOverlap(claim.text, snippet.text) })).sort((a, b) => b.score - a.score);
      const best = scored[0];
      if (best && best.score >= 0.12) {
        const record = phase2State.academic.records.find((item) => item.id === best.snippet.record_id);
        if (record) links.push({
          id: `link-${simpleHash(`${claim.id}|${best.snippet.id}`)}`, claim_id: claim.id, record_id: record.id,
          evidence_id: best.snippet.id, relation: "supports", support_score: Math.min(1, best.score),
          status: "needs-review", issues: ["本机按词项重合度匹配，请人工核对上下文与原意。"], verified_at: null,
        });
        comments.push(localCitationComment(claim, "candidate", "找到候选证据，需人工核对原意。"));
      } else comments.push(localCitationComment(claim, "unlinked", "尚未找到足以支撑该论断的原文片段。"));
    });
    const requiredClaims = claims.filter((claim) => claim.requires_citation !== false);
    const supportedClaims = new Set(links.filter((link) => link.status === "verified" && link.relation === "supports").map((link) => link.claim_id));
    const supportedCount = requiredClaims.filter((claim) => supportedClaims.has(claim.id)).length;
    return {
      links,
      comments,
      required_claim_count: requiredClaims.length,
      supported_claim_count: supportedCount,
      coverage: requiredClaims.length ? supportedCount / requiredClaims.length : 1,
    };
  }

  function localCitationComment(claim, status, message) {
    return {
      id: `review-${simpleHash(`${claim.id}|${status}|${message}`)}`,
      category: "citation",
      severity: claim.requires_citation === false ? "warning" : "error",
      message,
      recommendation: "回到原文核对论断、证据片段与引用语境。",
      location: String(claim.section || ""),
      claim_id: claim.id,
      record_id: null,
      evidence_id: null,
      resolved: false,
      text: claim.text,
      status,
    };
  }

  function isCanonicalCitationAudit(audit, claims) {
    return responseValidators.validateCitationAudit(audit, claims);
  }

  function lexicalOverlap(left, right) {
    const leftTerms = new Set(significantTerms(left));
    const rightTerms = new Set(significantTerms(right));
    if (!leftTerms.size || !rightTerms.size) return 0;
    return [...leftTerms].filter((term) => rightTerms.has(term)).length / Math.max(1, Math.min(leftTerms.size, rightTerms.size));
  }

  function validAcademicLinks(raw, claims) {
    if (!Array.isArray(raw)) return [];
    const recordIds = new Set(phase2State.academic.records.map((record) => record.id));
    const evidenceById = new Map(phase2State.academic.evidence.map((snippet) => [snippet.id, snippet]));
    const claimIds = new Set(claims.map((claim) => claim.id));
    return raw.filter((link) => link && claimIds.has(String(link.claim_id)) && recordIds.has(String(link.record_id)) && evidenceById.has(String(link.evidence_id)) && evidenceById.get(String(link.evidence_id)).record_id === String(link.record_id)).map((link, index) => ({
      id: String(link.id || `link-${index}`), claim_id: String(link.claim_id), record_id: String(link.record_id), evidence_id: String(link.evidence_id),
      relation: String(link.relation || "supports"), support_score: Number(link.support_score) || 0,
      status: String(link.status || "needs-review"), issues: Array.isArray(link.issues) ? link.issues.map(String) : [], verified_at: link.verified_at == null ? null : String(link.verified_at),
    }));
  }

  function academicCandidateLinks(claims, maxRecords = MAX_ACADEMIC_RECORDS) {
    const selection = academicEvidenceSelection(maxRecords);
    const allowedRecords = new Set(selection.record_ids);
    const allowedEvidence = new Set(selection.evidence_ids);
    const existing = validAcademicLinks(phase2State.academic.claim_links, claims)
      .filter((link) => allowedRecords.has(link.record_id) && allowedEvidence.has(link.evidence_id));
    const linkedClaims = new Set(existing.map((link) => link.claim_id));
    const candidates = validAcademicLinks(localClaimAudit(claims).links, claims)
      .filter((link) => !linkedClaims.has(link.claim_id) && allowedRecords.has(link.record_id) && allowedEvidence.has(link.evidence_id));
    return [...existing, ...candidates].slice(0, 1000);
  }

  function normalizeClaimComments(raw, claims, links) {
    if (Array.isArray(raw) && raw.length) return raw.map((comment, index) => typeof comment === "string" ? { claim_id: claims[index]?.id || "", text: claims[index]?.text || "", status: "note", message: comment } : {
      claim_id: String(comment?.claim_id || claims[index]?.id || ""), text: String(comment?.text || claims[index]?.text || ""), status: String(comment?.status || "note"), message: String(comment?.message || comment?.comment || ""),
    });
    return claims.map((claim) => ({ claim_id: claim.id, text: claim.text, status: links.some((link) => link.claim_id === claim.id) ? "linked" : "unlinked", message: links.some((link) => link.claim_id === claim.id) ? "已有证据链接，请继续核对引用语境。" : "尚未链接到证据。" }));
  }

  function renderAcademicClaimLinks() {
    const coverage = phase2State.academic.coverage;
    const percentage = coverage !== null && coverage !== "" && Number.isFinite(Number(coverage)) ? Math.round(Number(coverage) * (Number(coverage) <= 1 ? 100 : 1)) : null;
    els.academicCoverage.textContent = percentage === null ? "覆盖率 —" : `覆盖率 ${percentage}%`;
    const comments = phase2State.academic.claim_comments || [];
    const links = phase2State.academic.claim_links || [];
    els.academicClaimLinks.replaceChildren();
    els.academicClaimLinks.classList.toggle("is-empty", !comments.length && !links.length);
    if (!comments.length && !links.length) {
      const recoveredCount = Array.isArray(phase2State.academic.recovered_claims) ? phase2State.academic.recovered_claims.length : 0;
      const p = document.createElement("p"); p.textContent = recoveredCount
        ? `项目中已恢复 ${recoveredCount} 条历史论断记录；为避免污染当前稿件，未自动填入，请粘贴本稿论断后重新核验。`
        : "核验结果会区分已有证据、部分支撑和待补证据"; els.academicClaimLinks.append(p); updateReviewHub(); return;
    }
    comments.forEach((comment) => {
      const link = links.find((item) => item.claim_id === comment.claim_id);
      const snippet = link ? phase2State.academic.evidence.find((item) => item.id === link.evidence_id) : null;
      const record = link ? phase2State.academic.records.find((item) => item.id === link.record_id) : null;
      const article = document.createElement("article"); article.className = `claim-link ${link ? "is-linked" : "is-unlinked"}`;
      const badge = document.createElement("b"); badge.textContent = link ? "候选支撑" : "待补证据";
      const claim = document.createElement("p"); claim.textContent = comment.text || comment.message;
      const note = document.createElement("small"); note.textContent = link && snippet ? `${record ? citationLabel(record) : link.record_id}｜${snippet.text.slice(0, 120)}${snippet.text.length > 120 ? "…" : ""}` : comment.message;
      article.append(badge, claim, note); els.academicClaimLinks.append(article);
    });
    updateReviewHub();
  }

  async function formatAcademicCitations() {
    const records = phase2State.academic.records;
    if (!records.length) { toast("请先导入参考文献", "warning"); return; }
    const projectId = requireActiveProject("格式化参考文献");
    if (!projectId) return;
    const inputOperation = captureAcademicOperation(projectId, "citations");
    setButtonBusy(els.academicFormatCitationsButton, true, "正在格式化…");
    try {
      const style = els.academicCitationStyle.value;
      const result = await progressiveAcademicV2(`/api/v2/projects/${encodeURIComponent(projectId)}/academic/bibliography`, { method: "POST", body: { record_ids: records.map((record) => record.id), style } }, () => ({ items: records.map((record, index) => ({ record_id: record.id, text: formatAcademicReference(record, style, index) })) }), false);
      if (academicOperationIsStale(inputOperation)) return;
      const raw = Array.isArray(result.data?.items) ? result.data.items : Array.isArray(result.data?.citations) ? result.data.citations : Array.isArray(result.data) ? result.data : [];
      if (result.source === "server" && !raw.length) throw new Error("参考文献服务没有返回格式化条目");
      if (result.source === "server") {
        const expectedIds = new Set(records.map((record) => String(record.id)));
        const allStrings = raw.every((item) => typeof item === "string" && item.trim());
        const allObjects = raw.every((item) => item && typeof item === "object");
        const returnedIds = allObjects ? raw.map((item) => String(item.record_id || "")) : [];
        const objectItemsMatch = allObjects && returnedIds.every((id) => id && expectedIds.has(id))
          && new Set(returnedIds).size === expectedIds.size
          && raw.every((item) => String(item.text || item.citation || item.formatted || "").trim());
        if (raw.length !== records.length || Number(result.data?.count) !== raw.length || (!allStrings && !objectItemsMatch)) throw new Error("参考文献服务没有返回与请求记录一一对应的条目");
      }
      phase2State.academic.citations = raw.map((item, index) => ({
        record_id: String(item?.record_id || records[index]?.id || ""),
        text: String(typeof item === "string" ? item : item?.text || item?.citation || item?.formatted || "").trim(),
      })).filter((item) => item.text);
      if (result.source === "server" && !phase2State.academic.citations.length) throw new Error("参考文献服务返回的条目缺少正文");
      renderAcademicCitations(); persistPhase2State(); toast(result.source === "server" ? "参考文献表已由项目服务格式化" : "格式化服务执行失败；已按本地预览模式生成", result.source === "server" ? "success" : "info");
    } catch (error) { if (!academicOperationIsStale(inputOperation, error)) toast(readError(error, "参考文献格式化未完成"), "error"); }
    finally { finishAcademicOperation(inputOperation, els.academicFormatCitationsButton); }
  }

  function formatAcademicReference(record, style, index) {
    const authors = academicAuthorLabel(record.authors) || "作者信息待补";
    const year = record.issued_year || "日期待补";
    const container = record.container_title || record.publisher || "";
    const detail = [record.volume, record.issue ? `(${record.issue})` : "", record.pages].filter(Boolean).join(":");
    const locator = record.doi ? `DOI:${record.doi}` : record.url || "";
    if (style === "apa") return `${authors}. (${year}). ${record.title}. ${[container, detail, locator].filter(Boolean).join(", ")}.`;
    if (style === "mla") return `${authors}. “${record.title}.” ${[container, year, detail, locator].filter(Boolean).join(", ")}.`;
    if (style === "chicago") return `${authors}. “${record.title}.” ${[container, year, detail, locator].filter(Boolean).join(", ")}.`;
    const typeMark = /book|monograph/i.test(record.type) ? "M" : /thesis/i.test(record.type) ? "D" : "J";
    return `[${index + 1}] ${authors}. ${record.title}[${typeMark}]. ${[container, year, detail, locator].filter(Boolean).join(", ")}.`;
  }

  function renderAcademicCitations() {
    const items = phase2State.academic.citations || [];
    els.academicCitationOutput.replaceChildren();
    els.academicCitationOutput.classList.toggle("is-empty", !items.length);
    if (!items.length) {
      const p = document.createElement("p"); p.textContent = "格式化结果将在这里显示"; els.academicCitationOutput.append(p); return;
    }
    const list = document.createElement("ol");
    items.forEach((item) => { const li = document.createElement("li"); li.textContent = item.text; list.append(li); });
    const copy = document.createElement("button"); copy.type = "button"; copy.className = "mini-button"; copy.textContent = "复制参考文献表";
    copy.addEventListener("click", () => copyPlainText(items.map((item) => item.text).join("\n"), "参考文献表已复制"));
    const append = document.createElement("button"); append.type = "button"; append.className = "mini-button"; append.textContent = "追加参考文献";
    const projectId = String(phase2State.project_id || "");
    append.addEventListener("click", () => {
      if (appendAcademicContent("citations", items, projectId)) append.disabled = true;
    });
    els.academicCitationOutput.append(list, copy, append);
  }

  function academicContentBlocks(kind, value) {
    if (kind === "citations") {
      return [{ tag: "h2", text: "参考文献" }, ...value.map((item) => ({ tag: "p", text: String(item.text || "") }))];
    }
    if (typeof value === "string") return [{ tag: "h2", text: "研究提纲（待完善）" }, { tag: "p", text: value }];
    const isAbstract = value.output_kind === "abstract";
    const blocks = [{ tag: "h2", text: isAbstract ? "研究摘要" : "研究提纲（待完善）" }];
    if (value.abstract || value.summary) blocks.push({ tag: "p", text: String(value.abstract || value.summary) });
    const sections = Array.isArray(value.sections) ? value.sections : Array.isArray(value.outline) ? value.outline : Array.isArray(value.items) ? value.items : [];
    sections.forEach((section) => {
      blocks.push({ tag: "h3", text: String(typeof section === "string" ? section : section.heading || section.title || "提纲项") });
      if (section && typeof section === "object") {
        const guidance = section.guidance || section.purpose || section.description || section.content;
        if (guidance) blocks.push({ tag: "p", text: String(guidance) });
        const points = section.points || section.key_points;
        if (Array.isArray(points)) points.forEach((point) => blocks.push({ tag: "p", text: String(point) }));
        if (Array.isArray(section.questions) && section.questions.length) blocks.push({ tag: "p", text: `研究问题：${section.questions.join("；")}` });
      }
    });
    if (Array.isArray(value.placeholders) && value.placeholders.length) blocks.push({ tag: "p", text: `待补信息：${value.placeholders.join("；")}` });
    return blocks;
  }

  function appendAcademicContent(kind, value, projectId) {
    const currentValue = kind === "citations" ? phase2State.academic.citations : phase2State.academic.outline;
    if (String(phase2State.project_id || "") !== projectId || currentValue !== value) {
      toast("研究结果已变化，请使用当前项目的最新结果", "warning");
      return false;
    }
    if (phase2State.brief.scenario_pack_id !== "academic") {
      activateScenario("academic");
      toast("已切换到学术研究场景，请按当前研究任务重新生成结果后再追加", "warning");
      return false;
    }
    const hasDocument = Boolean(els.documentTitle.value.trim() || documentPlainText());
    if (hasDocument && phase2State.document_stale) {
      toast("当前保留的是上一版草稿，请先生成当前学术任务的母稿，再追加研究结果", "warning");
      focusProjectControl("briefCard");
      return false;
    }
    const blocks = academicContentBlocks(kind, value).filter((block) => block.text.trim());
    if (blocks.length < 2) { toast("研究结果尚无可追加正文，请先补充内容", "warning"); return false; }
    const fragment = document.createDocumentFragment();
    blocks.forEach((block) => {
      const node = document.createElement(block.tag);
      node.textContent = normalizeGeneratedPunctuation(block.text);
      fragment.append(node);
    });
    if (!hasDocument) {
      els.documentTitle.value = phase2State.academic.title || els.topic.value.trim() || "研究草稿";
      appState.document.execution = null;
      phase2State.document_stale = false;
    }
    els.documentEditor.append(fragment);
    els.generationHero.classList.add("is-hidden");
    els.documentWorkspace.classList.remove("is-hidden");
    handleDocumentInput();
    renderDocumentExecution();
    focusProjectControl("documentEditor");
    toast(kind === "citations" ? "参考文献已追加到母稿末尾，请核对正文引文与编号" : "研究结果已追加到母稿末尾，请继续完善论证与原文依据", "success");
    return true;
  }

  function selectedAcademicTask() {
    const tasks = {
      "literature-review": { documentType: "文献综述", recipeId: "literature-review", label: "文献综述提纲", action: "生成综述提纲" },
      "research-outline": { documentType: "研究提纲", recipeId: "research-outline", label: "研究提纲", action: "生成研究提纲" },
      abstract: { documentType: "摘要", recipeId: "research-abstract", label: "研究摘要", action: "生成研究摘要" },
      rebuttal: { documentType: "审稿回复", recipeId: "reviewer-response", label: "审稿回复", action: "生成逐条回复" },
    };
    const requested = els.academicTaskType?.value || phase2State.academic.task_type || "literature-review";
    const id = tasks[requested] ? requested : "literature-review";
    return { id, ...tasks[id] };
  }

  function academicBriefPayload() {
    const title = els.academicTitle.value.trim() || phase2State.academic.title || els.topic.value.trim();
    const question = els.academicGoal.value.trim() || phase2State.academic.goal || els.purpose.value.trim() || title;
    const task = selectedAcademicTask();
    return {
      title,
      research_question: question,
      discipline: "",
      purpose: question,
      audience: els.audience.value.trim() || "学术读者",
      document_type: task.documentType,
      language: phase2State.brief.target_language || "zh-CN",
      keywords: phase2State.brief.keywords.split(/[，,、;；\s]+/).map((item) => item.trim()).filter(Boolean).slice(0, 30),
      constraints: boundedTextList([els.requirements.value, phase2State.brief.constraints], 500, 32),
      method_notes: "",
      record_ids: phase2State.academic.records.map((record) => record.id),
    };
  }

  function updateAcademicPrimaryAction() {
    if (!els.academicOutlineButton) return;
    els.academicOutlineButton.textContent = selectedAcademicTask().action;
  }

  async function generateAcademicOutline() {
    const task = selectedAcademicTask();
    if (task.id === "rebuttal") { await generateAcademicRebuttal(); return; }
    if (!els.academicTitle.value.trim()) { els.academicTitle.focus(); toast("请先填写题目或研究问题", "warning"); return; }
    if (!phase2State.academic.records.length) { toast("请先导入真实参考文献", "warning"); return; }
    const projectId = requireActiveProject("生成研究提纲");
    if (!projectId) return;
    syncPhase2StateFromUI();
    const inputOperation = captureAcademicOperation(projectId, "outline");
    setButtonBusy(els.academicOutlineButton, true, "正在生成…");
    try {
      const isAbstract = task.id === "abstract";
      const claims = academicClaims();
      const links = academicCandidateLinks(claims, 1000);
      const academicBase = `/api/v2/projects/${encodeURIComponent(projectId)}/academic`;
      const path = isAbstract ? `${academicBase}/abstract` : `${academicBase}/outline`;
      const body = isAbstract
        ? { ...academicBriefPayload(), document_type: task.documentType, claims, links, max_characters: 800 }
        : { ...academicBriefPayload(), document_type: task.documentType, evidence_ids: phase2State.academic.evidence.map((item) => item.id).slice(0, 1000) };
      const result = await progressiveAcademicV2(path, { method: "POST", body }, isAbstract ? () => ({ abstract: localAcademicAbstract(claims) }) : localAcademicOutline);
      if (academicOperationIsStale(inputOperation)) return;
      if (result.source === "server") {
        const valid = isAbstract
          ? isCanonicalAcademicAbstract(result.data?.abstract, body)
          : isCanonicalAcademicOutline(result.data?.outline, body);
        if (!valid) throw new Error(isAbstract ? "摘要服务没有返回可追溯的完整正文" : "研究提纲服务没有返回可追溯的完整结构");
      }
      const abstractDraft = isAbstract ? result.data?.abstract || result.data : null;
      const rawOutline = result.data?.outline || result.data;
      const outline = isAbstract
        ? { title: els.academicTitle.value.trim(), abstract: String(abstractDraft?.text || ""), record_ids: abstractDraft?.record_ids || [], claim_ids: abstractDraft?.claim_ids || [], placeholders: abstractDraft?.placeholders || [], output_kind: "abstract", task_type: task.id }
        : typeof rawOutline === "string"
          ? { title: els.academicTitle.value.trim(), summary: rawOutline, sections: [], task_type: task.id }
          : { ...rawOutline, task_type: task.id };
      const hasOutline = typeof outline === "string" ? Boolean(outline.trim()) : Boolean(outline && typeof outline === "object" && (outline.title || (Array.isArray(outline.sections) && outline.sections.length)));
      if (result.source === "server" && (!hasOutline || (isAbstract && !outline.abstract))) throw new Error(isAbstract ? "摘要服务没有返回可用正文" : "研究提纲服务没有返回可用内容");
      phase2State.academic.outline = outline;
      renderAcademicOutline(); persistPhase2State(); toast(result.source === "server" ? `${task.label}已由项目服务生成` : `${task.label}服务执行失败；已按本地预览模式生成`, result.source === "server" ? "success" : "info");
    } catch (error) { if (!academicOperationIsStale(inputOperation, error)) toast(readError(error, "学术写作生成未完成"), "error"); }
    finally { finishAcademicOperation(inputOperation, els.academicOutlineButton); }
  }

  function isCanonicalAcademicOutline(outline, requestBody) {
    return (!outline?.task_type || outline.task_type === selectedAcademicTask().id) && Boolean(responseValidators?.validateAcademicOutline?.(outline, {
      recordIds: requestBody.record_ids || [],
    }));
  }

  function isCanonicalAcademicAbstract(abstract, requestBody) {
    return Boolean(responseValidators?.validateAcademicAbstract?.(abstract, {
      recordIds: requestBody.record_ids || [],
      claimIds: (requestBody.claims || []).map((claim) => String(claim.id)),
    }));
  }

  function localAcademicOutline() {
    const topic = phase2State.academic.title || "研究主题";
    const task = selectedAcademicTask();
    const recipe = workspaceContext.findRecipe("academic", task.recipeId);
    const methodology = recipe?.[4]?.methodology;
    const themes = phase2State.academic.matrix_meta?.themes || uniqueAcademicThemes(phase2State.academic.records);
    return {
      title: topic,
      task_type: task.id,
      summary: `围绕“${topic}”整理${task.label}。当前已导入 ${phase2State.academic.records.length} 篇文献、提取 ${phase2State.academic.evidence.length} 条证据；结构来自所选写作配方，具体论证仍需依据原文补充。`,
      record_ids: phase2State.academic.records.map((record) => record.id),
      sections: (methodology?.headings || []).map((heading, index) => ({
        heading,
        guidance: heading === "主题脉络" && themes.length
          ? `围绕${themes.slice(0, 5).join("、")}等主题比较既有文献，不逐篇堆砌摘要。`
          : methodology.section_purposes[index] || "请补充本节的可定位依据与论证。",
      })),
    };
  }

  function localAcademicAbstract(claims) {
    const topic = phase2State.academic.title || "研究主题";
    const goal = phase2State.academic.goal || "梳理研究问题与证据边界";
    const linkedClaims = new Set(academicCandidateLinks(claims, 1000).map((link) => link.claim_id));
    const placeholders = claims.filter((claim) => !linkedClaims.has(claim.id)).map((claim) => `待补证据：${claim.text}`).slice(0, 20);
    return {
      text: `本文围绕“${topic}”展开，旨在${goal}。研究基于当前项目已导入的 ${phase2State.academic.records.length} 条文献记录与 ${phase2State.academic.evidence.length} 条原文证据，按问题、方法、发现和局限建立比较框架，并对核心论断逐项核验引用覆盖。现阶段结果仅呈现已提供材料能够支撑的内容；证据不足之处保留待补标记，最终结论需结合原文与实际研究过程复核。`,
      record_ids: phase2State.academic.records.map((record) => record.id).slice(0, 1000),
      claim_ids: claims.map((claim) => claim.id),
      placeholders,
    };
  }

  function renderAcademicOutline() {
    const outline = phase2State.academic.outline;
    els.academicOutline.replaceChildren();
    els.academicOutline.classList.toggle("is-empty", !outline);
    if (!outline) { const p = document.createElement("p"); p.textContent = "题目、摘要与提纲将在这里生成"; els.academicOutline.append(p); return; }
    if (typeof outline === "string") { const p = document.createElement("p"); p.className = "outline-long-text"; p.textContent = outline; els.academicOutline.append(p); appendAcademicOutlineAction(outline); return; }
    const title = document.createElement("h3"); title.textContent = String(outline.title || phase2State.academic.title || "研究提纲");
    els.academicOutline.append(title);
    const taskLabels = { "literature-review": "文献综述提纲", "research-outline": "研究提纲", abstract: "研究摘要", rebuttal: "审稿回复", "research-paper": "研究论文提纲" };
    const taskLabel = taskLabels[outline.task_type || outline.output_kind];
    if (taskLabel) { const label = document.createElement("small"); label.className = "academic-placeholder-note"; label.textContent = `${taskLabel} · 本地规则整理`; els.academicOutline.append(label); }
    if (outline.abstract || outline.summary) { const abstract = document.createElement("p"); abstract.className = "academic-abstract"; abstract.textContent = String(outline.abstract || outline.summary); els.academicOutline.append(abstract); }
    if (Array.isArray(outline.placeholders) && outline.placeholders.length) {
      const notice = document.createElement("small"); notice.className = "academic-placeholder-note"; notice.textContent = `待补信息：${outline.placeholders.join("；")}`; els.academicOutline.append(notice);
    }
    const rawSections = Array.isArray(outline.sections) ? outline.sections : Array.isArray(outline.outline) ? outline.outline : Array.isArray(outline.items) ? outline.items : [];
    if (rawSections.length) {
      const list = document.createElement("ol");
      rawSections.forEach((section) => {
        const li = document.createElement("li");
        const heading = document.createElement("strong"); heading.textContent = String(typeof section === "string" ? section : section.heading || section.title || "提纲项");
        li.append(heading);
        const guidanceValue = typeof section === "object" ? section.guidance || section.purpose || section.description || section.content : "";
        if (guidanceValue) { const guidance = document.createElement("p"); guidance.textContent = String(guidanceValue); li.append(guidance); }
        const points = typeof section === "object" && Array.isArray(section.points || section.key_points) ? (section.points || section.key_points) : [];
        if (points.length) { const small = document.createElement("small"); small.textContent = points.join("；"); li.append(small); }
        const questions = typeof section === "object" && Array.isArray(section.questions) ? section.questions : [];
        if (questions.length) { const small = document.createElement("small"); small.textContent = `研究问题：${questions.join("；")}`; li.append(small); }
        list.append(li);
      });
      els.academicOutline.append(list);
    }
    appendAcademicOutlineAction(outline);
  }

  function appendAcademicOutlineAction(outline) {
    const append = document.createElement("button"); append.type = "button"; append.className = "mini-button"; append.textContent = "放入当前母稿";
    const projectId = String(phase2State.project_id || "");
    append.addEventListener("click", () => {
      if (appendAcademicContent("outline", outline, projectId)) append.disabled = true;
    });
    els.academicOutline.append(append);
  }

  async function generateAcademicRebuttal() {
    const commentTexts = splitReviewerComments(els.academicReviewerComments.value);
    if (!commentTexts.length) { els.academicReviewerComments.focus(); toast("请先填写审稿意见", "warning"); return; }
    const projectId = requireActiveProject("生成审稿回复");
    if (!projectId) return;
    const inputOperation = captureAcademicOperation(projectId, "rebuttal");
    const comments = commentTexts.map((message, index) => ({
      id: `review-${simpleHash(`${index}|${message}`)}`,
      category: "style",
      severity: "warning",
      message,
      recommendation: "请结合实际修改逐条回应",
      location: "",
      claim_id: null,
      record_id: null,
      evidence_id: null,
      resolved: false,
    }));
    setButtonBusy(els.academicRebuttalButton, true, "正在起草…");
    try {
      const changes = els.academicManuscriptChanges.value.trim();
      const changeMap = changes ? Object.fromEntries(comments.map((comment) => [comment.id, changes])) : {};
      const result = await progressiveV2(`/api/v2/projects/${encodeURIComponent(projectId)}/academic/rebuttal`, { method: "POST", body: { comments, changes: changeMap } }, () => ({ items: localRebuttal(commentTexts, changes) }));
      if (academicOperationIsStale(inputOperation)) return;
      const raw = Array.isArray(result.data?.items) ? result.data.items : Array.isArray(result.data?.responses) ? result.data.responses : Array.isArray(result.data) ? result.data : [];
      if (result.source === "server" && !raw.length) throw new Error("审稿回复服务没有返回可用条目");
      phase2State.academic.rebuttal = raw.map((item, index) => typeof item === "string" ? { comment: commentTexts[index] || `意见 ${index + 1}`, response: item, change_location: "" } : {
        comment: String(item?.comment || item?.reviewer_comment || commentTexts[index] || `意见 ${index + 1}`),
        response: String(item?.response || item?.reply || item?.text || ""),
        change_location: String(item?.change_location || item?.location || item?.manuscript_change || ""),
      }).filter((item) => item.response);
      if (!phase2State.academic.rebuttal.length) {
        if (result.source === "server") throw new Error("审稿回复服务返回的条目缺少正文");
        phase2State.academic.rebuttal = localRebuttal(commentTexts, changes);
      }
      renderAcademicRebuttal(); persistPhase2State(); toast(result.source === "server" ? "逐条审稿回复已由项目服务生成" : "回复服务执行失败；已按本地预览模式生成", result.source === "server" ? "success" : "info");
    } catch (error) { if (!academicOperationIsStale(inputOperation, error)) toast(readError(error, "审稿回复生成未完成"), "error"); }
    finally { finishAcademicOperation(inputOperation, els.academicRebuttalButton); }
  }

  function splitReviewerComments(value) {
    const text = String(value || "").trim();
    if (!text) return [];
    const blocks = text.split(/\n\s*\n+|(?=意见\s*\d+\s*[：:])/).map((item) => item.trim()).filter(Boolean);
    return (blocks.length > 1 ? blocks : text.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)).slice(0, 200);
  }

  function localRebuttal(comments, changes) {
    return comments.map((comment, index) => ({
      comment,
      response: changes
        ? `感谢审稿人的细致意见。我们已记录并依据该意见对稿件作出核对，当前修改说明为：${changes}。提交前将再次核准具体页码、段落与表述。`
        : "感谢审稿人的建设性意见。我们认同该问题需要进一步说明，拟补充相应依据并完善论证。请在定稿前填写实际修改内容和准确位置。",
      change_location: changes ? "请依据定稿补充页码与段落位置" : `待处理意见 ${index + 1}`,
    }));
  }

  function renderAcademicRebuttal() {
    const items = phase2State.academic.rebuttal || [];
    els.academicRebuttalOutput.replaceChildren();
    els.academicRebuttalOutput.classList.toggle("is-empty", !items.length);
    if (!items.length) { const p = document.createElement("p"); p.textContent = "回复将保持礼貌、具体，并标注尚待补充的信息"; els.academicRebuttalOutput.append(p); return; }
    items.forEach((item, index) => {
      const article = document.createElement("article"); article.className = "rebuttal-item";
      const heading = document.createElement("div");
      const number = document.createElement("b"); number.textContent = `意见 ${String(index + 1).padStart(2, "0")}`;
      const location = document.createElement("span"); location.textContent = item.change_location || "位置待核对";
      heading.append(number, location);
      const comment = document.createElement("blockquote"); comment.textContent = item.comment;
      const response = document.createElement("p"); response.textContent = item.response;
      const copy = document.createElement("button"); copy.type = "button"; copy.className = "mini-button"; copy.textContent = "复制本条回复";
      copy.addEventListener("click", () => copyPlainText(item.response, "本条回复已复制"));
      article.append(heading, comment, response, copy); els.academicRebuttalOutput.append(article);
    });
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
      if (Array.isArray(data.document_types) && data.document_types.length) {
        const selectedDocumentType = appState.form.document_type;
        replaceOptions(els.documentType, data.document_types);
        ensureDocumentTypeOption(selectedDocumentType);
        els.documentType.value = selectedDocumentType;
        reconcileTaskContext("restore", { invalidate: false, persist: false, reloadMethodology: false });
      }
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
      if (!methodologyCatalogReady) {
        methodologyCatalog = fallbackMethodologyCatalog(els.documentType.value || appState.form.document_type);
        mergeActiveRecipeMethodology();
        methodologyCatalogReady = true;
        renderMethodologyCatalog(false);
      }
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
    const requestContext = {
      requestSerial,
      projectSerial: projectSwitchSerial,
      projectId: String(phase2State.project_id || ""),
      documentType,
      contextSignature: taskContextSignature(),
    };
    const responseIsStale = () => !workspaceContext.catalogRequestMatches(requestContext, {
      requestSerial: catalogRequestSerial,
      projectSerial: projectSwitchSerial,
      projectId: String(phase2State.project_id || ""),
      documentType: els.documentType.value || appState.form.document_type,
      contextSignature: taskContextSignature(),
    });
    methodologyCatalogReady = false;
    try {
      const data = await apiRequest(`/api/methodologies?document_type=${encodeURIComponent(documentType)}`);
      if (responseIsStale()) return;
      if (data?.document_type && String(data.document_type) !== String(documentType)) throw new Error("方法论目录与当前文种不匹配");
      methodologyCatalog = {
        titleFormulas: Array.isArray(data.title_formulas) ? data.title_formulas : [],
        contentMethodologies: Array.isArray(data.content_methodologies) ? data.content_methodologies : [],
        defaults: Array.isArray(data.default_title_formula_ids) ? data.default_title_formula_ids : [],
        defaultMethodology: String(data.default_content_methodology_id || ""),
      };
      mergeActiveRecipeMethodology();
      methodologyCatalogReady = true;
      renderMethodologyCatalog(resetToDefaults);
    } catch (error) {
      if (responseIsStale()) return;
      methodologyCatalog = fallbackMethodologyCatalog(documentType);
      mergeActiveRecipeMethodology();
      methodologyCatalogReady = true;
      renderMethodologyCatalog(resetToDefaults);
      console.info("Methodology catalog unavailable; using compact built-in choices.", error);
    }
  }

  function activeRecipeMethodology() {
    const context = activeRecipeContext();
    const method = context.methodology;
    return {
      id: method.id,
      name: method.name,
      summary: method.summary,
      logic: method.logic,
      headings: [...method.headings],
      section_purposes: [...method.section_purposes],
      fact_strategy: method.fact_strategy,
      applicable_document_types: [context.documentType],
      recipe_override: true,
    };
  }

  function mergeActiveRecipeMethodology() {
    const recipeMethod = activeRecipeMethodology();
    methodologyCatalog.contentMethodologies = [
      recipeMethod,
      ...methodologyCatalog.contentMethodologies.filter((method) => (
        method.id !== recipeMethod.id && method.name !== recipeMethod.name
      )),
    ];
    methodologyCatalog.defaultMethodology = recipeMethod.id;
  }

  function renderMethodologyCatalog(resetToDefaults) {
    const previousMethodId = String(appState.form.content_methodology_id || "");
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
    if (previousMethodId && previousMethodId !== appState.form.content_methodology_id
      && (phase2State.master_asset_id || documentPlainText())) {
      clearTaskDerivedOutputs(activeRecipeContext());
    }
    scheduleSave();
    schedulePhase2Save();
  }

  function updateMethodologyView({ persist = true } = {}) {
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
    syncFormState();
    if (persist) scheduleSave();
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

  function generationMethodologyPayload() {
    // Built-in recipes are resolved by ID on the server. Treating them as custom
    // structures loses their scenario-specific section semantics.
    return customMethodologyPayload();
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
    if (!requireModelConnection()) return false;
    syncFormState();
    if (!appState.form.topic.trim()) {
      els.topic.focus();
      els.topic.closest(".field").classList.add("has-error");
      toast("请先填写写作主题", "warning");
      return false;
    }
    els.topic.closest(".field").classList.remove("has-error");
    if (els.contentMethodology.value === "custom" && !customMethodologyPayload()) {
      els.customMethodologyDetails.open = true;
      els.customMethodologySteps.focus();
      toast("请先填写自定义结构步骤", "warning");
      return false;
    }
    showLoading("正在起草文稿", "梳理事实材料，搭建标题与段落结构……");
    const requestSerial = ++generationRequestSerial;
    const inputOperation = captureInputOperation();
    try {
      if (documentPlainText()) createSnapshot("生成前的版本", false);
      const payload = {
        ...appState.form,
        materials: currentFactualMaterialText(),
        custom_methodology: methodologyCatalogReady
          ? generationMethodologyPayload()
          : appState.form.custom_methodology,
        selected_title: phase2State.selected_title || undefined,
        style_references: appState.styleReferences,
        fact_lock: appState.form.factLock,
        live: settings.mode === "api",
        provider: providerPayload(),
      };
      delete payload.factLock;
      const result = await apiRequest("/api/generate", { method: "POST", body: payload });
      if (requestSerial !== generationRequestSerial || inputOperationIsStale(inputOperation)) return false;
      const hasGeneratedBody = typeof result?.content === "string" && result.content.trim()
        || Array.isArray(result?.outline) && result.outline.some((item) => String(item?.content || "").trim());
      if (!hasGeneratedBody) throw new Error("生成服务没有返回可用正文");
      applyGeneratedDocument(result);
      focusProjectControl("documentExecution");
      createSnapshot("生成初稿", false);
      toast("初稿已生成，可继续逐段修改", "success");
      return true;
    } catch (error) {
      if (requestSerial !== generationRequestSerial || inputOperationIsStale(inputOperation, error)) return false;
      toast(readError(error, "生成失败，请稍后重试"), "error");
      return false;
    } finally {
      if (requestSerial === generationRequestSerial) hideLoading();
    }
  }

  async function refreshTitleCandidates() {
    if (!requireModelConnection()) return;
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
    const inputOperation = captureInputOperation();
    try {
      const payload = {
        document_type: appState.form.document_type,
        topic: appState.form.topic,
        purpose: appState.form.purpose,
        audience: appState.form.audience,
        materials: currentFactualMaterialText(),
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
      if (inputOperationIsStale(inputOperation)) return;
      const candidates = normalizeCandidates(result.candidates || result.title_candidates || result.titles || [], result.recommended_title || result.title);
      if (!candidates.length) throw new Error("标题服务没有返回可用候选");
      appState.document.candidates = candidates;
      appState.document.title_execution = executionMode.execution(result);
      if (!appState.document.title) {
        appState.document.title = String(result.recommended_title || appState.document.candidates[0]?.title || "");
        els.documentTitle.value = appState.document.title;
        phase2State.selected_title = appState.document.title;
        invalidateSavedBriefBinding();
        renderDocumentContextStatus();
        updateProjectWorkflowStatus();
      }
      renderCandidates(); scheduleSave(); schedulePhase2Save(); toast(`标题已生成 · ${executionMode.execution(result)?.label || "来源未注明"}`, "success");
    } catch (error) { if (!inputOperationIsStale(inputOperation, error)) toast(readError(error, "标题生成失败"), "error"); }
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
    appState.document = { title, candidates, outline, html: "", execution: executionMode.execution(result), title_execution: executionMode.execution(result) };
    renderDocumentExecution();
    invalidateDocumentDerivedState();
    els.documentTitle.value = title;
    renderContent(result.content, outline);
    appState.document.html = sanitizeHtml(els.documentEditor.innerHTML);
    phase2State.document_stale = false;
    phase2State.output_binding_hash = currentBriefBindingHash();
    renderCandidates();
    renderOutline();
    renderDocumentContextStatus();
    els.generationHero.classList.add("is-hidden");
    els.documentWorkspace.classList.remove("is-hidden");
    els.paperType.textContent = appState.form.document_type;
    resetReviewView();
    updateCounts();
    updatePhase2Summaries();
    scheduleSave();
    schedulePhase2Save();
  }

  function renderContent(content, outline) {
    const fragment = document.createDocumentFragment();
    const headingKey = (text) => String(text || "").trim().replace(/^#{1,6}\s+/, "").replace(/\s+/g, " ");
    const outlineHeadings = new Set(outline.map((item) => headingKey(item.heading)));
    const source = String(content || "").trim();
    const lines = source ? source.split(/\n+/).map((line) => line.trim()).filter(Boolean) : [];
    if (!lines.length && outline.length) {
      outline.forEach((item) => lines.push(item.heading, item.content));
    }
    lines.forEach((line, index) => {
      const isHeading = outlineHeadings.has(headingKey(line)) || /^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|\d+[.、])/.test(line);
      const node = document.createElement(isHeading ? "h2" : "p");
      node.textContent = line;
      if (isHeading) node.id = `section-${index}`;
      fragment.append(node);
    });
    els.documentEditor.replaceChildren(fragment);
  }

  function renderCandidates() {
    if (els.titleExecution) els.titleExecution.textContent = appState.document.candidates?.length
      ? `${executionMode.execution(appState.document.title_execution)?.label || "候选来源未记录"} · 分数仅作写法参考`
      : "候选将按综合评分由高到低排列；分数仅作写法参考";
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
      const adopted = Boolean(phase2State.selected_title) && candidate.title === phase2State.selected_title;
      button.className = `title-candidate${adopted ? " is-selected" : ""}`;
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
      action.textContent = adopted ? "已采用" : "一键采用";
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
    const items = !phase2State.document_stale && headings.length
      ? headings.map((heading) => ({ heading: heading.textContent || "未命名章节", content: "" }))
      : appState.document.outline;
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
    if (!requireModelConnection()) return false;
    const content = documentPlainText();
    if (!content) { toast("请先生成或输入正文", "warning"); return false; }
    const inputOperation = captureInputOperation();
    showLoading("正在检查文稿", "核对结构、表达、事实与待补信息……");
    try {
      const [reviewResult, auditResult] = await Promise.allSettled([
        apiRequest("/api/review", { method: "POST", body: { title: els.documentTitle.value.trim(), content, document_type: els.documentType.value, materials: currentFactualMaterialText(), live: settings.mode === "api", provider: providerPayload() } }),
        apiRequest("/api/fact-audit", { method: "POST", body: { title: els.documentTitle.value.trim(), content, materials: currentFactualMaterialText() } }),
      ]);
      if (inputOperationIsStale(inputOperation)) return false;
      const validReview = reviewResult.status === "fulfilled" && isValidLegacyReview(reviewResult.value);
      const validAudit = auditResult.status === "fulfilled" && isValidFactAudit(auditResult.value);
      if (!validReview && !validAudit) {
        if (reviewResult.status === "rejected") throw reviewResult.reason;
        if (auditResult.status === "rejected") throw auditResult.reason;
        throw new Error("审校服务没有返回有效结果");
      }
      appState.review = validReview ? reviewResult.value : null;
      appState.factAudit = validAudit ? auditResult.value : null;
      if (appState.review) renderReview();
      else renderReviewUnavailable("语言与格式检查未完成，事实审校结果仍可查看。");
      if (appState.factAudit) renderFactAudit();
      else renderFactAuditUnavailable("事实审校未完成，语言与格式检查结果仍可查看。");
      scheduleSave();
      toast(validReview && validAudit ? "质量检查已完成" : "已完成部分检查，请查看提示", validReview && validAudit ? "success" : "warning");
      return true;
    } catch (error) {
      if (!inputOperationIsStale(inputOperation, error)) toast(readError(error, "检查失败，请稍后重试"), "error");
      return false;
    }
    finally { hideLoading(); }
  }

  function isValidLegacyReview(review) {
    return Boolean(review && typeof review === "object"
      && Number.isFinite(Number(review.score)) && Number(review.score) >= 0 && Number(review.score) <= 100
      && Array.isArray(review.issues) && review.metrics && typeof review.metrics === "object");
  }

  function isValidFactAudit(audit) {
    const coverage = Number(audit?.metrics?.evidence_coverage_percent);
    return Boolean(audit && typeof audit === "object" && audit.metrics && typeof audit.metrics === "object"
      && Number.isFinite(coverage) && coverage >= 0 && coverage <= 100
      && Array.isArray(audit.facts) && Array.isArray(audit.sentences) && Array.isArray(audit.issues));
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
    const factMetric = !currentFactualMaterialText().trim() ? "未核验" : !appState.factAudit ? "待重试" : !Number(auditMetrics.claim_sentence_count) ? "无待核陈述" : hasFactConflict ? "疑似冲突" : unverifiedFacts ? `${unverifiedFacts}项待核` : "有材料依据";
    const dimensionIds = sceneReviewDimensionIds();
    const metricItems = currentScenario().review_dimensions.map((label, index) => [label, index === 2 ? factMetric : reviewDimensionText(dimensionIds[index])]);
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
    updatePhase2Summaries();
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
    els.qualityMetrics.replaceChildren(...currentScenario().review_dimensions.map((label, index) => {
      const row = document.createElement("div"); const span = document.createElement("span"); const value = document.createElement("b");
      span.textContent = label; value.textContent = index === 2 && appState.factAudit ? `${appState.factAudit.metrics?.evidence_coverage_percent || 0}% 有依据` : "待重试";
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
    if (!content) { toast("请先生成或输入正文", "warning"); return false; }
    setButtonBusy(els.exportDocxButton, true, "正在生成…");
    try {
      const filename = safeFilename(els.documentTitle.value || "公文") + ".docx";
      const response = await fetch("/api/export/docx", { method: "POST", headers: requestHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ title: els.documentTitle.value.trim() || "公文", content, template_style: selectedTemplate(), metadata: { document_type: els.documentType.value, issuing_org: els.issuingOrg.value.trim(), issue_date: els.issueDate.value }, filename }), signal: phase2State.project_id ? projectRequestController.signal : undefined });
      if (!response.ok) throw await responseError(response);
      downloadBlob(await response.blob(), filename);
      toast("Word 文件已生成", "success");
      return true;
    } catch (error) { toast(readError(error, "导出失败，请稍后重试"), "error"); return false; }
    finally { setButtonBusy(els.exportDocxButton, false); }
  }

  async function apiRequest(path, { method = "GET", body } = {}) {
    const options = { method, headers: requestHeaders({ Accept: "application/json" }) };
    if (String(path).startsWith("/api/v2/projects/") || (phase2State.project_id && method !== "GET")) options.signal = projectRequestController.signal;
    const timeoutSignal = typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(method === "GET" ? 15000 : 300000) : null;
    if (timeoutSignal) options.signal = options.signal && typeof AbortSignal.any === "function"
      ? AbortSignal.any([options.signal, timeoutSignal]) : options.signal || timeoutSignal;
    if (body !== undefined) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
    let response;
    try { response = await fetch(path, options); }
    catch (error) {
      if (error?.name !== "AbortError") setConnection(false);
      if (error?.name === "TimeoutError") throw new Error("服务响应超时，请检查连接后重试");
      throw error;
    }
    if (!response.ok) {
      const error = await responseError(response);
      if (response.status === 401 && accessTokenRequired) {
        clearAccessToken();
        showAccessGate("访问令牌已失效，请重新输入。");
      }
      throw error;
    }
    const result = await response.json();
    if (serviceConnected === false) setConnection(true);
    return result;
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
        card.classList.toggle("is-selected", checkbox.checked); handleStyleReferencesChanged();
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
      remove.addEventListener("click", () => { appState.styleReferences = appState.styleReferences.filter((item) => item.id !== reference.id); handleStyleReferencesChanged(); });
      chip.append(label, remove); els.selectedReferences.append(chip);
    });
    els.selectedArticleCount.textContent = `已选择 ${references.length} 篇`;
    updatePhase2Summaries();
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
    handleStyleReferencesChanged();
  }

  function handleStyleReferencesChanged() {
    renderSelectedReferences();
    if (invalidateSavedBriefBinding()) {
      renderVariants();
      updateProjectWorkflowStatus();
      renderDocumentContextStatus();
    }
    scheduleSave();
    schedulePhase2Save();
  }

  async function deleteArticle(articleId, articleTitle = "这篇文章") {
    if (!window.confirm(`确定从本地文章来源库删除“${articleTitle}”吗？`)) return;
    try {
      await apiRequest(`/api/articles/${encodeURIComponent(articleId)}`, { method: "DELETE" });
      appState.styleReferences = appState.styleReferences.filter((item) => item.id !== articleId);
      handleStyleReferencesChanged(); await loadArticles(); toast("文章已从本地库删除", "success");
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
    const saveSerial = ++serverDocumentSaveSerial;
    const saveOperation = currentDocumentSaveOperation();
    setButtonBusy(els.saveServerDocumentButton, true, "正在保存…");
    try {
      const result = await apiRequest("/api/documents", { method: "POST", body: {
        id: saveOperation.documentId || undefined,
        expected_version: saveOperation.documentId ? saveOperation.documentVersion : 0,
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
      const currentVersion = Number(result?.current_version);
      if (!result || typeof result !== "object" || !String(result.id || "").trim()
        || !Number.isInteger(currentVersion) || currentVersion < 1) throw new Error("文稿服务没有返回有效的文稿 ID 与版本");
      if (saveSerial !== serverDocumentSaveSerial || !workspaceContext.documentSaveResponseMatches(
        saveOperation,
        currentDocumentSaveOperation(),
        result,
      )) {
        els.serverDocumentStatus.textContent = "编辑区已变化 · 本次结果保留在服务端文稿库";
        await loadServerDocuments();
        return;
      }
      appState.serverDocumentId = String(result.id);
      appState.serverDocumentVersion = currentVersion;
      els.serverDocumentStatus.textContent = `已保存 · 第 ${appState.serverDocumentVersion} 版`;
      persistState(); await loadServerDocuments(); toast("文稿和版本已保存到本机服务端", "success");
    } catch (error) {
      if (saveSerial !== serverDocumentSaveSerial
        || !workspaceContext.documentSaveResponseMatches(saveOperation, currentDocumentSaveOperation(), {
          id: saveOperation.documentId || "pending-document",
        })) return;
      if (error?.payload?.error?.code === "version_conflict") {
        els.serverDocumentStatus.textContent = "检测到其他页面的新版本，请先重新打开后再保存";
        await loadServerDocuments();
      }
      toast(readError(error, "服务端保存失败"), "error");
    }
    finally { if (saveSerial === serverDocumentSaveSerial) setButtonBusy(els.saveServerDocumentButton, false); }
  }

  async function openServerDocument(documentId) {
    const inputOperation = captureInputOperation();
    try {
      const record = await apiRequest(`/api/documents/${encodeURIComponent(documentId)}`);
      if (inputOperationIsStale(inputOperation)) return;
      const currentVersion = Number(record?.current_version);
      if (!record || typeof record !== "object" || String(record.id || "") !== String(documentId)
        || !Number.isInteger(currentVersion) || currentVersion < 1
        || !String(record.title || "").trim() || !String(record.content || "").trim()) throw new Error("文稿服务没有返回匹配的完整文稿");
      const metadata = record.metadata && typeof record.metadata === "object" ? record.metadata : {};
      const nextState = freshState();
      nextState.form = { ...nextState.form, ...(metadata.form || {}), document_type: record.document_type || metadata.form?.document_type || "工作总结" };
      nextState.styleReferences = Array.isArray(metadata.style_references) ? metadata.style_references.map(normalizeArticleReference).filter((item) => item.id).slice(0, 8) : [];
      nextState.exportMeta = { ...nextState.exportMeta, ...(metadata.export_meta || {}) };
      nextState.document = { title: record.title || "", html: metadata.document_html ? sanitizeHtml(String(metadata.document_html)) : htmlFromPlainText(record.content || ""), candidates: [], outline: [] };
      nextState.serverDocumentId = String(record.id);
      nextState.serverDocumentVersion = currentVersion;
      openStandaloneDocumentState(nextState);
      els.serverDocumentsModal.close();
      toast(`已在独立文稿中打开第 ${currentVersion} 版`, "success");
    } catch (error) { if (!inputOperationIsStale(inputOperation, error)) toast(readError(error, "文稿打开失败"), "error"); }
  }

  async function deleteServerDocument(documentId) {
    if (!window.confirm("确定删除这份服务端文稿及其全部版本吗？")) return;
    try {
      await apiRequest(`/api/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
      if (appState.serverDocumentId === documentId) { appState.serverDocumentId = ""; appState.serverDocumentVersion = 0; els.serverDocumentStatus.textContent = "当前文稿已从服务端删除"; persistState(); }
      await loadServerDocuments(); toast("服务端文稿已删除", "success");
    } catch (error) { toast(readError(error, "文稿删除失败"), "error"); }
  }

  function openStandaloneDocumentState(rawState) {
    captureCurrentProjectDraft();
    projectSwitchSerial += 1;
    projectListRequestSerial += 1;
    invalidateMethodologyCatalogRequest();
    projectRequestController.abort(new DOMException("已切换到独立文稿", "AbortError"));
    projectRequestController = new AbortController();
    projectAssetsLoading = false;
    resetProjectActionButtons();

    const stateDefaults = freshState();
    const nextState = rawState && typeof rawState === "object" ? structuredCloneSafe(rawState) : {};
    appState = {
      ...stateDefaults,
      ...nextState,
      form: { ...stateDefaults.form, ...(nextState.form || {}) },
      document: { ...stateDefaults.document, ...(nextState.document || {}) },
      exportMeta: { ...stateDefaults.exportMeta, ...(nextState.exportMeta || {}) },
    };
    appState.styleReferences = Array.isArray(nextState.styleReferences)
      ? nextState.styleReferences.map(normalizeArticleReference).filter((item) => item.id).slice(0, 8)
      : [];
    appState.checklist = Array.from({ length: 6 }, (_, index) => Boolean(Array.isArray(nextState.checklist) && nextState.checklist[index]));
    appState.serverDocumentId = String(nextState.serverDocumentId || "");
    appState.serverDocumentVersion = Math.max(0, Number(nextState.serverDocumentVersion) || 0);
    appState.document.html = normalizeGeneratedPunctuation(appState.document.html || "");

    const phaseDefaults = freshPhase2State();
    const documentType = String(appState.form.document_type || "实施方案");
    const context = workspaceContext.resolveStandaloneDocumentContext({
      contentType: "official-document",
      channel: "document",
      packId: "gongwen",
      recipeId: "implementation-plan",
      documentType,
      academicTaskType: "literature-review",
    });
    phase2State = {
      ...phaseDefaults,
      view: phase2State.view,
      local_draft_mode: phase2State.local_draft_mode,
      projects: phase2State.projects,
      project_drafts: phase2State.project_drafts,
      standalone_document: true,
      brief: {
        ...phaseDefaults.brief,
        content_type: context.contentType,
        channel: context.channel,
        scenario_pack_id: context.scenarioPackId,
        recipe_id: context.recipeId,
        recipe_content_type: context.documentType,
      },
      selected_title: String(appState.document.title || ""),
      academic: {
        ...phaseDefaults.academic,
        task_type: context.academicTaskType || phaseDefaults.academic.task_type,
        title: appState.form.topic,
        goal: appState.form.purpose,
      },
    };
    ensureDocumentTypeOption(context.documentType);
    appState.form.document_type = context.documentType;
    invalidateDocumentDerivedState();
    applyStateToUI();
    applyPhase2StateToUI();
    phase2State.document_stale = false;
    phase2State.output_binding_hash = "";
    renderProjectOptions();
    updateProjectWorkflowStatus();
    renderDocumentContextStatus();
    resetReviewView();
    renderAcademicIntegrity();
    updatePhase2Summaries();
    persistState();
    persistPhase2State();
    void loadMethodologyCatalog(false);
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
    const nextState = freshState();
    nextState.form = { ...nextState.form, ...(metadata.form || {}), document_type: version.document_type || metadata.form?.document_type || "工作总结" };
    nextState.styleReferences = Array.isArray(metadata.style_references) ? metadata.style_references.map(normalizeArticleReference).filter((item) => item.id).slice(0, 8) : [];
    nextState.exportMeta = { ...nextState.exportMeta, ...(metadata.export_meta || {}) };
    nextState.document = { title: version.title || "", html: metadata.document_html ? sanitizeHtml(String(metadata.document_html)) : htmlFromPlainText(version.content || ""), candidates: [], outline: [] };
    nextState.serverDocumentId = String(record.id || "");
    nextState.serverDocumentVersion = Number(record.current_version) || Number(version.version) || 1;
    openStandaloneDocumentState(nextState);
    els.serverDocumentsModal.close();
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
    error.status = response.status;
    return error;
  }

  function providerPayload() {
    if (settings.mode !== "api") return undefined;
    if (serverProvider.configured && !sessionApiKey && !settings.baseUrl && !settings.modelName) return undefined;
    const aliases = { deepseek: "openai", qwen: "openai", custom: "openai" };
    return { name: aliases[settings.providerName] || settings.providerName || "openai", model: settings.modelName || undefined, api_key: sessionApiKey || undefined, base_url: settings.baseUrl || undefined };
  }

  function readError(error, fallback) { return error instanceof Error && error.message ? error.message : fallback; }

  function handleFormInput(event = null) {
    if (event?.target === els.documentType) {
      reconcileTaskContext("document_type");
      return;
    }
    const previousSemanticState = JSON.stringify(appState.form);
    const previousDocumentType = appState.form.document_type;
    syncFormState();
    if (phase2State.brief.scenario_pack_id === "academic") {
      els.academicTitle.value = els.topic.value.trim();
      els.academicGoal.value = els.purpose.value.trim();
      phase2State.academic.title = els.academicTitle.value;
      phase2State.academic.goal = els.academicGoal.value;
    }
    syncPhase2StateFromUI({ invalidate: false });
    if (previousSemanticState !== JSON.stringify(appState.form)) clearTaskDerivedOutputs(activeRecipeContext());
    const briefBindingInvalidated = invalidateSavedBriefBinding();
    if (appState.review || appState.factAudit) {
      appState.review = null; appState.factAudit = null; resetReviewView();
    }
    els.documentBadge.textContent = appState.form.document_type;
    els.paperType.textContent = appState.form.document_type;
    updateCounts();
    clearTimeout(factTimer);
    factTimer = window.setTimeout(updateFacts, 350);
    if (previousDocumentType !== appState.form.document_type) loadMethodologyCatalog(true);
    if (briefBindingInvalidated) {
      renderVariants();
      updateProjectWorkflowStatus();
      renderDocumentContextStatus();
      schedulePhase2Save();
    }
    updatePhase2Summaries();
    scheduleSave();
  }

  function handleDocumentInput(event = null) {
    const userEditedTitle = event?.target === els.documentTitle;
    if (userEditedTitle) {
      phase2State.selected_title = els.documentTitle.value.trim();
    }
    appState.document.title = els.documentTitle.value;
    appState.document.html = sanitizeHtml(els.documentEditor.innerHTML);
    invalidateDocumentDerivedState();
    resetReviewView();
    renderAcademicIntegrity();
    if (userEditedTitle && invalidateSavedBriefBinding()) {
      renderVariants();
      updateProjectWorkflowStatus();
    }
    renderDocumentContextStatus();
    updateCounts();
    renderOutline();
    updatePhase2Summaries();
    scheduleSave();
    schedulePhase2Save();
  }

  function syncFormState() {
    const contentMethodologyId = methodologyCatalogReady
      ? (els.contentMethodology?.value || "")
      : String(appState.form.content_methodology_id || "");
    const titleFormulaIds = methodologyCatalogReady
      ? selectedTitleFormulaIds()
      : (Array.isArray(appState.form.title_formula_ids) ? appState.form.title_formula_ids : []);
    const customMethodology = methodologyCatalogReady
      ? customMethodologyPayload()
      : (appState.form.custom_methodology || null);
    const customTitleFormula = methodologyCatalogReady
      ? customTitleFormulaPayload()
      : (appState.form.custom_title_formula || null);
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
      content_methodology_id: contentMethodologyId,
      custom_methodology: customMethodology,
      title_formula_ids: titleFormulaIds,
      title_count: Math.max(1, Math.min(20, Number(els.titleCount?.value) || 5)),
      custom_title_formula: customTitleFormula,
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
      updatePhase2Summaries();
      return;
    }
    const total = Object.values(groups).reduce((sum, values) => sum + values.length, 0);
    els.factHint.textContent = total ? `已从材料中识别 ${total} 项关键信息。` : "已读取材料，暂未识别到明确事实，可继续补充。";
    const labels = { dates: "时间", numbers: "数字", organizations: "机构", tasks: "任务" };
    Object.entries(groups).forEach(([key, values]) => {
      if (!values.length) return;
      const section = document.createElement("section"); section.className = `fact-group fact-group-${key}`;
      const head = document.createElement("h4"); head.className = "fact-group-heading";
      const marker = document.createElement("i"); marker.className = "fact-group-marker"; marker.setAttribute("aria-hidden", "true");
      const text = document.createElement("span"); text.textContent = labels[key]; head.append(marker, text);
      const list = document.createElement("div"); list.className = "fact-values";
      values.slice(0, key === "tasks" ? 4 : 6).forEach((value) => { const item = document.createElement("span"); item.className = "fact-tag"; item.textContent = value; item.title = value; list.append(item); });
      section.append(head, list); els.factGroups.append(section);
    });
    updatePhase2Summaries();
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
    const scene = currentScenario();
    if (documentPlainText()) createSnapshot("填写示例前的版本", false);
    const example = scene.example;
    ["topic", "purpose", "audience", "requirements", "materials"].forEach((field) => { els[field].value = example[field] || ""; });
    els.briefKeywords.value = example.keywords || "";
    els.briefConstraints.value = "";
    appState.styleCustom = false;
    const context = reconcileTaskContext("recipe", { invalidate: false, persist: false });
    syncFormState(); syncPhase2StateFromUI({ invalidate: false });
    clearTaskDerivedOutputs(context);
    invalidateSavedBriefBinding(); updateCounts(); updateFacts(); updatePhase2Summaries();
    scheduleSave(); schedulePhase2Save();
    toast(`${scene.name}示例已填入；原稿保留供对照，重新生成后再交付。`, "success");
  }

  async function importMaterialFile() {
    const file = els.materialFile.files?.[0]; if (!file) return;
    const projectId = String(phase2State.project_id || "");
    const operationSerial = projectSwitchSerial;
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error("文件请控制在 2MB 以内");
      const text = await file.text();
      if (projectOperationIsStale(projectId, operationSerial)) {
        toast("项目已切换，本次文件未导入", "info");
        return;
      }
      els.materials.value = [els.materials.value.trim(), text.trim()].filter(Boolean).join("\n\n");
      els.materialFileName.textContent = file.name;
      handleFormInput();
      toast("材料已导入", "success");
    } catch (error) { toast(readError(error, "文件读取失败"), "error"); }
    finally { els.materialFile.value = ""; }
  }

  function selectTitle(title) {
    phase2State.selected_title = title;
    appState.document.title = title;
    els.documentTitle.value = title;
    appState.review = null; appState.factAudit = null; resetReviewView();
    const invalidated = invalidateSavedBriefBinding();
    if (invalidated && documentPlainText()) phase2State.document_stale = true;
    renderDocumentContextStatus();
    updateProjectWorkflowStatus();
    renderCandidates();
    toast("已采用该标题，生成正文时将优先使用", "success");
    scheduleSave(); schedulePhase2Save();
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
    if (!requireModelConnection()) return;
    if (!savedSelection || !savedSelection.toString().trim()) { toast("请先选中需要改写的文字", "warning"); return; }
    const range = savedSelection.cloneRange();
    const text = range.toString();
    if (mode === "custom" && !instruction.trim()) { els.rewriteInstruction.focus(); return; }
    if (els.rewriteModal.open) els.rewriteModal.close();
    const inputOperation = captureInputOperation();
    hideSelectionToolbar();
    showLoading("正在改写选中内容", "保持事实不变，调整表达和句式……");
    try {
      const result = await apiRequest("/api/rewrite", { method: "POST", body: { text, document_type: els.documentType.value, instruction: instruction || rewriteInstruction(mode), mode, tone: appState.form.tone, live: settings.mode === "api", provider: providerPayload() } });
      if (inputOperationIsStale(inputOperation)) return;
      if (!result || typeof result !== "object" || !String(result.text || "").trim()) throw new Error("改写服务没有返回有效正文");
      if (!els.documentEditor.contains(range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement)) throw new Error("原文已发生变化，请重新选择");
      range.deleteContents();
      range.insertNode(document.createTextNode(String(result.text)));
      els.documentEditor.normalize();
      handleDocumentInput();
      createSnapshot("局部改写", false);
      toast(Array.isArray(result.changes) && result.changes.length ? result.changes.join("；") : "改写已完成", "success");
    } catch (error) { toast(readError(error, "改写失败，请稍后重试"), "error"); }
    finally { hideLoading(); savedSelection = null; }
  }

  function rewriteInstruction(mode) {
    return { polish: "提升表达的准确性和流畅度，保持当前场景与目标读者一致", concise: "删除重复和铺垫，保留全部事实并精简表达", expand: "围绕原意适度扩写，补充解释但不新增事实数据或研究结论", formal: `调整为适合${currentScenario().name}的专业表达，保持原意和事实边界` }[mode] || "优化表达";
  }

  function resetReviewView() {
    renderFactAudit();
    els.qualityScore.textContent = "—"; els.scoreRing.style.setProperty("--score", 0);
    els.qualityTitle.textContent = "文稿已更新"; els.qualitySummary.textContent = "请重新运行检查，以获取最新结果。";
    els.qualityMetrics.replaceChildren(...currentScenario().review_dimensions.map((label) => {
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
    if (els.serverProviderCard) els.serverProviderCard.hidden = false;
    els.serverProviderTitle.textContent = serverProvider.configured ? `服务端模型：${serverProvider.defaultModel || "模型名称未返回"}` : "服务端尚未配置模型";
    els.serverProviderDetail.textContent = serverProvider.configured
      ? `${serverProvider.providerName || "供应商未返回"} · API 模式下，将页面接口、模型和密钥留空即可使用该服务端连接。项目工作流也使用此连接。配置就绪不等于已通过连接测试。`
      : "当前没有服务端模型。可在下方填写页面临时连接用于单篇写作；项目母稿与变体的真实调用需先配置服务器模型。";
    if (serverProvider.configured && !settings.modelName && serverProvider.defaultModel) {
      els.modelName.placeholder = `服务端默认：${serverProvider.defaultModel}`;
    }
  }

  function openDrawer(drawer) {
    drawerReturnFocus = document.activeElement;
    els.drawerBackdrop.hidden = false;
    requestAnimationFrame(() => {
      els.drawerBackdrop.classList.add("is-visible"); drawer.classList.add("is-open");
      drawer.inert = false; drawer.setAttribute("aria-hidden", "false");
      $('button, input, select', drawer)?.focus();
    });
  }

  function closeDrawers() {
    const hadOpenDrawer = [els.settingsDrawer, els.historyDrawer].some((drawer) => drawer.classList.contains("is-open"));
    [els.settingsDrawer, els.historyDrawer].forEach((drawer) => { drawer.classList.remove("is-open"); drawer.inert = true; drawer.setAttribute("aria-hidden", "true"); });
    if (hadOpenDrawer && drawerReturnFocus?.isConnected) drawerReturnFocus.focus({ preventScroll: true });
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
      els.providerTestStatus.textContent = `服务端配置：${serverProvider.providerName} · ${serverProvider.defaultModel}；页面字段留空即使用它。测试连接会发起一次最小模型请求。`;
    }
  }

  async function testProviderConnection() {
    const operation = ++providerTestSerial;
    const provider = providerPayloadFromForm();
    if (provider && (!provider.model || !provider.api_key)) {
      toast("页面临时连接请同时填写模型名称和本页密钥；使用服务端默认连接时请清空这三项。", "warning");
      (!provider.model ? els.modelName : els.apiKey).focus();
      return;
    }
    if (!provider && !serverProvider.configured) { els.modelName.focus(); toast("请先填写模型名称", "warning"); return; }
    if (provider && !provider.model && !serverProvider.configured) { els.modelName.focus(); toast("请先填写模型名称", "warning"); return; }
    if (provider && els.providerName.value !== "openai" && !provider.base_url && !serverProvider.configured) { els.baseUrl.focus(); toast("请填写该兼容服务的接口地址", "warning"); return; }
    els.providerTestStatus.className = "connection-test";
    els.providerTestStatus.textContent = "正在发送最小连接测试……";
    setButtonBusy(els.testProviderButton, true, "正在测试…");
    try {
      const result = await apiRequest("/api/provider/test", { method: "POST", body: provider ? { provider } : {} });
      if (operation !== providerTestSerial) return;
      els.providerTestStatus.className = "connection-test success";
      els.providerTestStatus.textContent = `${result.message || "连接成功"}${result.meta?.model ? ` · ${result.meta.model}` : ""}`;
    } catch (error) {
      if (operation !== providerTestSerial) return;
      els.providerTestStatus.className = "connection-test error";
      els.providerTestStatus.textContent = readError(error, "连接测试失败");
    } finally { setButtonBusy(els.testProviderButton, false); }
  }

  function resetProviderTestStatus() {
    providerTestSerial += 1;
    els.providerTestStatus.className = "connection-test";
    els.providerTestStatus.textContent = "设置已变更，请重新测试连接。";
  }

  function saveSettings() {
    const mode = $('input[name="engineMode"]:checked')?.value || "demo";
    if (mode === "api" && !serverProvider.configured && !els.modelName.value.trim()) { els.modelName.focus(); toast("请填写模型名称", "warning"); return; }
    if (mode === "api" && !serverProvider.configured && els.providerName.value !== "openai" && !els.baseUrl.value.trim()) { els.baseUrl.focus(); toast("请填写该服务商的接口地址", "warning"); return; }
    const hasClientFields = Boolean(els.baseUrl.value.trim() || els.modelName.value.trim() || els.apiKey.value.trim());
    if (mode === "api" && hasClientFields && (!els.modelName.value.trim() || !els.apiKey.value.trim())) {
      toast("页面临时连接请同时填写模型名称和本页密钥；使用服务端默认连接时请清空这三项。", "warning");
      (!els.modelName.value.trim() ? els.modelName : els.apiKey).focus();
      return;
    }
    modelSettingsSerial += 1;
    sessionApiKey = els.apiKey.value.trim();
    settings = { mode, providerName: els.providerName.value, baseUrl: els.baseUrl.value.trim(), modelName: els.modelName.value.trim() };
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch (_) { /* private browsing */ }
    applySettingsStatus(); closeDrawers(); toast(mode === "api" ? `已选择 ${currentModelConnection().label}；点击生成后调用` : "已切换为模板演示 · 未调用大模型", "success");
  }

  function restoreSettings() {
    try { settings = { ...settings, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") }; }
    catch (_) { /* ignore corrupted local settings */ }
    delete settings.apiKey;
  }

  function applySettingsStatus() {
    const current = currentModelConnection();
    els.providerLabel.textContent = current.label;
    els.connectionLabel.textContent = serviceConnected === false ? "服务未连接" : serviceConnected === null ? "正在检查服务" : "服务已连接";
    els.connectionDot.classList.toggle("live", current.mode === "live" && current.ready && serviceConnected === true);
    els.engineBannerTitle.textContent = current.label;
    els.engineBannerDetail.textContent = serviceConnected === false ? "本地服务未连接，当前草稿仍保留。启动服务后点击“重新连接服务”。" : current.detail;
    els.engineBanner.dataset.mode = current.mode;
    els.retryConnectionButton.hidden = serviceConnected !== false;
    updateSettingsOverview();
  }

  function currentModelConnection() {
    return executionMode.connection({ settings, server: serverProvider, keyPresent: Boolean(sessionApiKey) });
  }

  function requireModelConnection({ project = false } = {}) {
    const current = currentModelConnection();
    if (current.mode === "local") return true;
    if (!current.ready || (project && !current.projectReady)) {
      openSettings();
      toast(project && current.source === "browser"
        ? "项目母稿与渠道变体使用服务端模型。当前是页面临时连接：可用“生成初稿”单篇写作，或清空页面连接字段后选用服务端配置。"
        : "真实模型连接尚未完成，请检查模型名称、接口和本页密钥。", "warning");
      return false;
    }
    return true;
  }

  function renderDocumentExecution() {
    const value = executionMode.execution(appState.document.execution);
    els.documentExecution.textContent = value ? `本稿生成来源：${value.label} · 编辑内容由你确认` : "本稿生成来源：未记录（历史稿或手工内容）";
  }

  async function retryServiceConnection() {
    setButtonBusy(els.retryConnectionButton, true, "正在重连…");
    try {
      const ready = await bootstrap();
      if (ready) { await loadArticleSources(); await initializePhase2Service(); toast("服务已重新连接，草稿已保留", "success"); }
      else toast("尚未连上本地服务，请确认服务已启动", "warning");
    } finally { setButtonBusy(els.retryConnectionButton, false); }
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
        appState.scenarioId = scenarioCatalog.profiles[saved.scenarioId] ? saved.scenarioId : scenarioWorkspace.inferScenario(appState.form.document_type);
        appState.styleCustom = saved.styleCustom ?? scenarioWorkspace.profile(appState.scenarioId).styles.some((style) => style.label === appState.form.reference_style);
        appState.styleReferences = Array.isArray(saved.styleReferences) ? saved.styleReferences.map(normalizeArticleReference).filter((item) => item.id).slice(0, 8) : [];
        appState.checklist = Array.from({ length: 6 }, (_, index) => Boolean(Array.isArray(saved.checklist) && saved.checklist[index]));
        appState.serverDocumentId = typeof saved.serverDocumentId === "string" ? saved.serverDocumentId : "";
        appState.serverDocumentVersion = Math.max(0, Number(saved.serverDocumentVersion) || 0);
        appState.document.html = normalizeGeneratedPunctuation(appState.document.html);
      }
    } catch (_) { appState = freshState(); }
  }

  function applyStateToUI() {
    renderDocumentExecution();
    const form = appState.form;
    renderScenarioControls(scenarioWorkspace.profile(appState.scenarioId || scenarioWorkspace.inferScenario(form.document_type)), form);
    ensureDocumentTypeOption(form.document_type);
    els.documentType.value = form.document_type; els.topic.value = form.topic; els.purpose.value = form.purpose;
    els.audience.value = form.audience; els.length.value = normalizeLength(form.length); els.requirements.value = form.requirements;
    els.materials.value = form.materials; els.factLock.checked = form.factLock !== false;
    els.titleCount.value = String(Math.max(1, Math.min(20, Number(form.title_count) || 5)));
    const savedCustomMethod = form.content_methodology_id === "custom"
      && form.custom_methodology && typeof form.custom_methodology === "object"
      ? form.custom_methodology
      : null;
    els.customMethodologyName.value = String(savedCustomMethod?.name || "");
    els.customMethodologySteps.value = Array.isArray(savedCustomMethod?.steps) ? savedCustomMethod.steps.join("\n") : "";
    els.customMethodologyDetails.open = Boolean(savedCustomMethod);
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
    if (appState.review) renderReview(); else resetReviewView();
    renderFactAudit(); renderSelectedReferences(); applySettingsStatus();
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
    openStandaloneDocumentState(snapshot.state);
    closeDrawers();
    toast("已在独立文稿中恢复所选版本", "success");
  }

  function invalidateDocumentDerivedState() {
    appState.review = null;
    appState.factAudit = null;
    phase2State.academic.integrity = null;
    phase2State.academic.coverage = null;
  }

  function handleKeyboard(event) {
    const open = [els.settingsDrawer, els.historyDrawer].find((drawer) => drawer.classList.contains("is-open"));
    if (open) {
      if (event.key === "Escape") { event.preventDefault(); closeDrawers(); }
      if (event.key === "Tab") {
        const controls = $$('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]', open).filter((el) => el.getClientRects().length);
        const first = controls[0]; const last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
      return;
    }
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
    serviceConnected = Boolean(connected);
    els.connectionDot.classList.toggle("connected", connected);
    applySettingsStatus();
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
