(function exposeWorkspaceContext(root, factory) {
  const catalog = root.YanzhangScenarioCatalog || (typeof require === "function" ? require("./scenario_catalog.js") : null);
  const api = factory(catalog);
  if (typeof module === "object" && module.exports) module.exports = api;
  root.YanzhangWorkspaceContext = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createWorkspaceContext(catalog) {
  "use strict";

  const PACK_CONTENT_TYPES = Object.freeze({
    gongwen: Object.freeze(["official-document", "leadership-speech", "research-report"]),
    workplace: Object.freeze(["general-writing"]),
    media: Object.freeze(["news-release", "general-writing"]),
    academic: Object.freeze(["academic-paper"]),
  });

  const DEFAULT_CONTENT_TYPE = Object.freeze({
    gongwen: "official-document",
    workplace: "general-writing",
    media: "news-release",
    academic: "academic-paper",
  });

  if (!catalog?.recipes) throw new Error("场景配方目录未加载");
  function contentFamily(packId, id) {
    if (packId === "academic") return "academic-paper";
    if (packId === "workplace") return "general-writing";
    if (packId === "media") return id === "press-release" ? "news-release" : "general-writing";
    return id === "leadership-speech" ? "leadership-speech" : id === "research-report" ? "research-report" : "official-document";
  }
  const RECIPE_CATALOG = Object.freeze(Object.fromEntries(Object.entries(catalog.recipes).map(([packId, recipes]) => [
    packId, Object.freeze(recipes.map((item) => Object.freeze([
      item.id, item.name, item.content_type, Object.freeze([...item.channels]), Object.freeze({
        contentType: contentFamily(packId, item.id),
        methodology: Object.freeze({
          id: `recipe-${item.id}`, name: `${item.name}结构法`, summary: item.summary,
          logic: item.sections.map((section) => section.title).join(" → "),
          headings: Object.freeze(item.sections.map((section) => section.title)),
          section_purposes: Object.freeze(item.sections.map((section) => section.purpose)),
          fact_strategy: item.fact_strategy,
        }),
      }),
    ]))),
  ])));

  const CONTENT_TYPE_DEFAULTS = Object.freeze({
    "official-document": Object.freeze({ packId: "gongwen", recipeId: "implementation-plan" }),
    "leadership-speech": Object.freeze({ packId: "gongwen", recipeId: "leadership-speech" }),
    "research-report": Object.freeze({ packId: "gongwen", recipeId: "research-report" }),
    "news-release": Object.freeze({ packId: "media", recipeId: "press-release" }),
    "academic-paper": Object.freeze({ packId: "academic", recipeId: "literature-review" }),
    "general-writing": Object.freeze({ packId: "workplace", recipeId: "business-proposal" }),
  });

  const ACADEMIC_TASK_BY_RECIPE = Object.freeze({
    "literature-review": "literature-review",
    "research-outline": "research-outline",
    "research-abstract": "abstract",
    "reviewer-response": "rebuttal",
  });
  const RECIPE_BY_ACADEMIC_TASK = Object.freeze(Object.fromEntries(
    Object.entries(ACADEMIC_TASK_BY_RECIPE).map(([recipeId, taskType]) => [taskType, recipeId]),
  ));

  function recipesFor(packId) {
    return RECIPE_CATALOG[packId] || RECIPE_CATALOG.gongwen;
  }

  function findRecipe(packId, recipeId) {
    return recipesFor(packId).find((item) => item[0] === recipeId) || null;
  }

  function locateDocumentType(documentType) {
    for (const [packId, recipes] of Object.entries(RECIPE_CATALOG)) {
      const match = recipes.find((item) => item[2] === documentType);
      if (match) return { packId, recipeId: match[0] };
    }
    return null;
  }

  function briefBindingSignature(input = {}) {
    const references = Array.isArray(input.styleReferences) ? input.styleReferences : [];
    const materialIds = Array.isArray(input.workspaceMaterialIds) ? input.workspaceMaterialIds : [];
    const formulaIds = Array.isArray(input.titleFormulaIds) ? input.titleFormulaIds : [];
    return JSON.stringify({
      payload: input.payload || {},
      content_type_family: String(input.contentTypeFamily || ""),
      deadline: String(input.deadline || ""),
      document_type: String(input.documentType || ""),
      reference_style: String(input.referenceStyle || ""),
      content_methodology_id: String(input.contentMethodologyId || ""),
      custom_methodology: input.customMethodology || null,
      selected_title: String(input.selectedTitle || ""),
      title_formula_ids: formulaIds.map(String),
      custom_title_formula: input.customTitleFormula || null,
      fact_lock: Boolean(input.factLock),
      materials_hash: String(input.materialsHash || ""),
      style_references: references.map((item) => [
        String(item?.id || ""),
        String(item?.url || ""),
        String(item?.source || item?.source_name || ""),
        String(item?.title || ""),
        String(item?.excerpt || item?.summary || ""),
        Array.isArray(item?.style_features)
          ? item.style_features.map(String)
          : String(item?.style_features || item?.style_summary || ""),
      ]),
      workspace_material_ids: materialIds.map(String),
    });
  }

  function generationInputSignature(input = {}) {
    return JSON.stringify({
      project_id: String(input.projectId || ""),
      brief_binding_hash: String(input.briefBindingHash || ""),
      document: input.document || {},
      expression: input.expression || {},
      variant: input.variant || {},
      academic: input.academic || {},
      model: Array.isArray(input.model) ? input.model.map(String) : [],
    });
  }

  function operationMatches(expected, current) {
    return Boolean(expected && current
      && Number(expected.projectSerial) === Number(current.projectSerial)
      && String(expected.projectId || "") === String(current.projectId || "")
      && String(expected.inputHash || "") === String(current.inputHash || ""));
  }

  function assetMatchesBinding(asset, expected = {}) {
    if (!asset || typeof asset !== "object") return false;
    if (expected.assetId && String(asset.id || "") !== String(expected.assetId)) return false;
    if (expected.requireProjectId && !String(asset.project_id || "")) return false;
    if (expected.projectId && asset.project_id !== undefined
      && String(asset.project_id || "") !== String(expected.projectId)) return false;
    const briefId = String(asset.brief_id || "");
    if (expected.requireBriefId && !briefId) return false;
    if (expected.briefId && briefId !== String(expected.briefId)) return false;
    return true;
  }

  function documentSaveResponseMatches(operation, current, response) {
    if (!operation || !current || !response || typeof response !== "object") return false;
    if (String(operation.documentId || "") !== String(current.documentId || "")) return false;
    if (Number(operation.documentVersion || 0) !== Number(current.documentVersion || 0)) return false;
    if (String(operation.editorHash || "") !== String(current.editorHash || "")) return false;
    if (Number(operation.projectSerial || 0) !== Number(current.projectSerial || 0)) return false;
    if (String(operation.projectId || "") !== String(current.projectId || "")) return false;
    if (!String(response.id || "")) return false;
    return !operation.documentId || String(response.id) === String(operation.documentId);
  }

  function catalogRequestMatches(operation, current) {
    return Boolean(operation && current
      && Number(operation.requestSerial) === Number(current.requestSerial)
      && Number(operation.projectSerial) === Number(current.projectSerial)
      && String(operation.projectId || "") === String(current.projectId || "")
      && String(operation.documentType || "") === String(current.documentType || "")
      && String(operation.contextSignature || "") === String(current.contextSignature || ""));
  }

  function resolveWorkspaceContext(input, source = "restore") {
    let packId = RECIPE_CATALOG[input.packId] ? input.packId : "gongwen";
    let recipeId = findRecipe(packId, input.recipeId)?.[0] || recipesFor(packId)[0][0];
    let contentType = String(input.contentType || DEFAULT_CONTENT_TYPE[packId]);
    let documentTypeOverride = "";

    if (source === "content_type" && CONTENT_TYPE_DEFAULTS[contentType]) {
      const defaults = CONTENT_TYPE_DEFAULTS[contentType];
      packId = defaults.packId;
      recipeId = defaults.recipeId;
      documentTypeOverride = defaults.documentType || "";
    } else if (source === "scenario_pack") {
      recipeId = findRecipe(packId, recipeId)?.[0] || recipesFor(packId)[0][0];
      contentType = DEFAULT_CONTENT_TYPE[packId];
    } else if (source === "document_type") {
      const located = locateDocumentType(String(input.documentType || ""));
      if (located) {
        packId = located.packId;
        recipeId = located.recipeId;
        contentType = findRecipe(packId, recipeId)[4].contentType;
      }
    } else if (source === "academic_task") {
      packId = "academic";
      recipeId = RECIPE_BY_ACADEMIC_TASK[input.academicTaskType] || "literature-review";
      contentType = "academic-paper";
    }

    const selectedRecipe = findRecipe(packId, recipeId) || recipesFor(packId)[0];
    const profile = selectedRecipe[4];
    contentType = profile.contentType;
    const allowedChannels = selectedRecipe[3];
    const requestedChannel = String(input.channel || "");
    const channel = source === "restore" && allowedChannels.includes(requestedChannel)
      ? requestedChannel
      : allowedChannels[0];

    return Object.freeze({
      scenarioPackId: packId,
      recipeId: selectedRecipe[0],
      contentType,
      channel,
      documentType: documentTypeOverride || selectedRecipe[2],
      academicTaskType: ACADEMIC_TASK_BY_RECIPE[selectedRecipe[0]] || "",
      methodology: profile.methodology,
      headings: profile.methodology.headings,
    });
  }

  function resolveStandaloneDocumentContext(input) {
    const requestedDocumentType = String(input?.documentType || "").trim();
    const resolved = resolveWorkspaceContext(input || {}, "document_type");
    if (!requestedDocumentType || locateDocumentType(requestedDocumentType)) return resolved;
    return Object.freeze({ ...resolved, documentType: requestedDocumentType });
  }

  return Object.freeze({
    ACADEMIC_TASK_BY_RECIPE,
    DEFAULT_CONTENT_TYPE,
    PACK_CONTENT_TYPES,
    RECIPE_CATALOG,
    assetMatchesBinding,
    briefBindingSignature,
    catalogRequestMatches,
    documentSaveResponseMatches,
    findRecipe,
    generationInputSignature,
    locateDocumentType,
    operationMatches,
    recipesFor,
    resolveStandaloneDocumentContext,
    resolveWorkspaceContext,
  });
});
