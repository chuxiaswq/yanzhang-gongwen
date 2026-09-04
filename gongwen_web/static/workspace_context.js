(function exposeWorkspaceContext(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.YanzhangWorkspaceContext = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createWorkspaceContext() {
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

  const recipe = (id, label, documentType, channels, contentType, method) =>
    Object.freeze([id, label, documentType, Object.freeze(channels), Object.freeze({
      contentType,
      methodology: Object.freeze({
        id: `recipe-${id}`,
        name: method.name,
        summary: method.summary,
        logic: method.logic,
        headings: Object.freeze(method.headings),
        section_purposes: Object.freeze(method.purposes),
        fact_strategy: method.factStrategy,
      }),
    })]);

  const RECIPE_CATALOG = Object.freeze({
    gongwen: Object.freeze([
      recipe("work-summary", "工作总结", "工作总结", ["document"], "official-document", {
        name: "回顾—成效—问题—提升法",
        summary: "由总体回顾进入成效证据，再以问题诊断承接下一步提升。",
        logic: "总体回顾 → 做法与证据 → 问题诊断 → 改进计划",
        headings: ["总体情况", "主要成效", "问题不足", "下一步安排"],
        purposes: ["交代背景、范围和总体判断。", "按事实归纳进展和成果。", "识别短板及其影响。", "明确改进方向和行动。"],
        factStrategy: "数字、日期、名称和成果仅使用已关联材料；缺少依据时保留待补标记。",
      }),
      recipe("briefing-material", "汇报材料", "汇报材料", ["document", "presentation"], "official-document", {
        name: "进展—亮点—问题—计划汇报法",
        summary: "按进展、亮点、问题和计划组织面向决策者的汇报。",
        logic: "总体进展 → 亮点证据 → 困难问题 → 工作计划",
        headings: ["工作进展", "亮点成效", "困难问题", "工作计划"],
        purposes: ["先给结论，再说明总体进度。", "选择有证据的代表性成果。", "区分现象、原因和影响。", "给出任务、责任和节点。"],
        factStrategy: "关键结论应绑定来源，推测性判断须明确标记。",
      }),
      recipe("leadership-speech", "领导讲话", "讲话稿", ["document"], "leadership-speech", {
        name: "共识—重点—责任动员法",
        summary: "以凝聚共识、部署重点和压实责任组织正式讲话。",
        logic: "统一认识 → 明确怎么干 → 压实谁来干",
        headings: ["提高站位，凝聚思想共识", "突出重点，推动任务落实", "压实责任，确保取得实效"],
        purposes: ["阐明意义和形势。", "部署重点任务和工作方法。", "提出责任、作风和实效要求。"],
        factStrategy: "事实用于支撑判断和部署，不把写法参考中的数据带入讲话。",
      }),
      recipe("research-report", "调研报告", "调研报告", ["document"], "research-report", {
        name: "概况—现状—问题—建议调研法",
        summary: "按调研范围、现状证据、问题成因和对策建议形成研究型报告。",
        logic: "调研概况 → 现状与成效 → 问题与原因 → 对策建议",
        headings: ["调研概况", "现状与成效", "问题与原因", "对策建议"],
        purposes: ["说明背景、对象、范围和方法边界。", "基于材料归纳现状、做法和成效。", "区分问题表现、影响和原因。", "提出与问题对应的可执行建议。"],
        factStrategy: "调研事实、数字和因果判断须有材料依据；建议与问题逐项对应。",
      }),
      recipe("implementation-plan", "实施方案", "实施方案", ["document"], "official-document", {
        name: "要求—目标—举措—步骤—保障路线图",
        summary: "从总体要求到任务、步骤和保障形成执行路线图。",
        logic: "总体原则 → 可检验目标 → 重点举措 → 时间路线 → 保障闭环",
        headings: ["总体要求", "工作目标", "重点举措", "实施步骤", "保障措施"],
        purposes: ["明确依据、原则和方向。", "定义可验证的目标状态。", "展开任务、责任和协同关系。", "明确阶段、节点和交付物。", "配置组织、资源和监督机制。"],
        factStrategy: "目标值、时间节点和责任主体必须来自已确认材料。",
      }),
      recipe("meeting-minutes", "会议纪要", "会议纪要", ["meeting", "document"], "official-document", {
        name: "会情—议定—分工—落实纪要法",
        summary: "把会议过程压缩为议定事项、责任分工和执行要求。",
        logic: "会议情况 → 议定事项 → 责任分工 → 落实要求",
        headings: ["会议情况", "议定事项", "责任分工", "落实要求"],
        purposes: ["记录时间、主题和必要参会信息。", "提炼明确结论和决策。", "关联责任人、期限和依赖。", "形成可跟踪的后续动作。"],
        factStrategy: "人名、时间、决策和任务状态逐项回查会议原始材料。",
      }),
    ]),
    workplace: Object.freeze([
      recipe("work-email", "工作邮件", "邮件", ["email"], "general-writing", {
        name: "主题—结论—信息—行动邮件法",
        summary: "用清晰主题、结论前置和明确行动降低沟通成本。",
        logic: "邮件主题 → 背景与结论 → 必要信息 → 下一步",
        headings: ["邮件主题", "背景与结论", "必要信息", "下一步"],
        purposes: ["让收件人快速识别事项和动作。", "用最少文字交代背景和核心结论。", "提供决策或执行所需事实。", "明确请求、责任与时间。"],
        factStrategy: "不得补写材料中未提供的承诺、期限或责任主体。",
      }),
      recipe("weekly-report", "周报", "周报", ["document", "email"], "general-writing", {
        name: "完成—进展—风险—计划周报法",
        summary: "按完成、进展、风险和下周计划快速同步工作。",
        logic: "本周完成 → 进行中 → 风险与协同 → 下周计划",
        headings: ["本周完成", "进行中", "风险与协同", "下周计划"],
        purposes: ["列出已产生的成果。", "说明进度和下一节点。", "暴露阻塞及所需支持。", "列出优先级和交付物。"],
        factStrategy: "完成状态和进度数字以工作记录为准。",
      }),
      recipe("business-proposal", "业务方案", "业务方案", ["document", "presentation"], "general-writing", {
        name: "问题—目标—方案—价值—风险决策法",
        summary: "从问题、目标、方案、收益和风险构建决策材料。",
        logic: "问题与机会 → 目标与原则 → 方案设计 → 预期价值 → 风险与推进",
        headings: ["问题与机会", "目标与原则", "方案设计", "预期价值", "风险与推进"],
        purposes: ["界定需要解决的业务问题。", "说明成功标准和边界。", "描述路径、资源和关键动作。", "说明收益及其计算依据。", "给出风险、应对和实施节奏。"],
        factStrategy: "收益数字、市场判断和比较结论应关联证据。",
      }),
      recipe("meeting-followup", "会议跟办清单", "会议跟办", ["meeting", "email"], "general-writing", {
        name: "结论—行动—依赖—确认跟办法",
        summary: "把讨论结果转化为责任明确、时间清晰的行动清单。",
        logic: "会议结论 → 行动项 → 依赖与风险 → 待确认事项",
        headings: ["会议结论", "行动项", "依赖与风险", "待确认事项"],
        purposes: ["只保留已经确认的决定。", "拆出动作、负责人、期限和状态。", "标记协同关系和阻塞。", "集中呈现尚需确认的信息。"],
        factStrategy: "行动项必须能在会议记录中定位；模糊责任以待确认为状态。",
      }),
      recipe("presentation-outline", "PPT 提纲", "PPT提纲", ["presentation"], "general-writing", {
        name: "结论—主线—逐页—行动演示法",
        summary: "把母稿压缩为结论先行、逐页单一重点的演示结构。",
        logic: "核心结论 → 叙事主线 → 逐页提纲 → 收束与行动",
        headings: ["核心结论", "叙事主线", "逐页提纲", "收束与行动"],
        purposes: ["用一句话明确演示希望听众记住什么。", "按问题、洞察和行动安排信息顺序。", "为每页设置结论式标题与三项以内要点。", "明确决策请求或下一步。"],
        factStrategy: "图表数字和结论均关联母稿或资料来源，缺少依据时保留待补标记。",
      }),
    ]),
    media: Object.freeze([
      recipe("press-release", "新闻稿", "新闻稿", ["web", "document"], "news-release", {
        name: "标题—导语—主体—背景新闻法",
        summary: "用标题、导语、主体和背景信息讲清事件价值。",
        logic: "标题 → 导语 → 主体 → 背景",
        headings: ["标题", "导语", "主体", "背景"],
        purposes: ["准确呈现最重要的新闻事实。", "集中交代核心事实和意义。", "按重要程度补充事实与引述。", "提供理解事件所需上下文。"],
        factStrategy: "新闻六要素、数字、引语和机构名称逐项绑定来源。",
      }),
      recipe("wechat-article", "公众号文章", "公众号文章", ["web"], "general-writing", {
        name: "价值—场景—内容—行动长文法",
        summary: "以清晰价值主张、场景化展开和行动收束形成长文。",
        logic: "标题与开场 → 问题场景 → 核心内容 → 总结与行动",
        headings: ["标题与开场", "问题场景", "核心内容", "总结与行动"],
        purposes: ["建立与读者相关的阅读理由。", "呈现背景、矛盾或机会。", "按层次展开事实与观点。", "回扣价值并给出下一步。"],
        factStrategy: "事实与观点分开表达；引用和数字关联可追溯材料。",
      }),
      recipe("social-post", "社交媒体文案", "社交媒体文案", ["social"], "general-writing", {
        name: "开场—正文—收束短文法",
        summary: "用单一焦点、简短价值和自然行动提示完成短文。",
        logic: "开场 → 正文 → 收束",
        headings: ["开场", "正文", "收束"],
        purposes: ["在首句给出最相关的信息。", "只保留一个核心观点和必要事实。", "自然邀请读者了解、反馈或行动。"],
        factStrategy: "不用未经材料支持的极限词、数字或效果承诺。",
      }),
      recipe("short-video-script", "短视频脚本", "短视频脚本", ["social"], "general-writing", {
        name: "钩子—节拍—转折—行动脚本法",
        summary: "按钩子、信息推进、转折和行动设计口播文字。",
        logic: "开场钩子 → 内容节拍 → 关键转折 → 行动提示",
        headings: ["开场钩子", "内容节拍", "关键转折", "行动提示"],
        purposes: ["快速建立问题或价值期待。", "按口播节奏逐步推进信息。", "突出核心认识或解决路径。", "用自然语言给出下一步。"],
        factStrategy: "案例、数据和效果表述必须来自已确认材料。",
      }),
    ]),
    academic: Object.freeze([
      recipe("literature-review", "文献综述", "文献综述", ["academic", "document"], "academic-paper", {
        name: "问题—主题—分歧—空白综述法",
        summary: "围绕研究问题组织主题、分歧、证据和研究空白。",
        logic: "问题与范围 → 主题脉络 → 证据与分歧 → 研究空白",
        headings: ["问题与范围", "主题脉络", "证据与分歧", "研究空白"],
        purposes: ["界定问题、概念和材料范围。", "按主题而非逐篇罗列组织研究。", "比较结论、方法与证据强度。", "从已有证据推导仍待回答的问题。"],
        factStrategy: "每项文献主张必须关联实际导入的来源和定位信息。",
      }),
      recipe("research-outline", "研究提纲", "研究提纲", ["academic", "document"], "academic-paper", {
        name: "问题—框架—方法—章节研究法",
        summary: "从研究问题、概念、方法到分析路径形成可执行提纲。",
        logic: "研究问题 → 分析框架 → 资料与方法 → 章节结构",
        headings: ["研究问题", "分析框架", "资料与方法", "章节结构"],
        purposes: ["形成明确、可回答的问题。", "定义概念、变量和关系。", "说明数据、样本和分析方法。", "让每章服务于研究问题。"],
        factStrategy: "方法和资料能力按用户提供条件陈述，不虚构数据可得性。",
      }),
      recipe("research-abstract", "研究摘要", "摘要", ["academic"], "academic-paper", {
        name: "背景—方法—结果—结论摘要法",
        summary: "用背景、方法、结果和结论压缩完整研究。",
        logic: "背景与目的 → 方法 → 结果 → 结论",
        headings: ["背景与目的", "方法", "结果", "结论"],
        purposes: ["说明问题及研究目的。", "概括数据和研究设计。", "准确呈现关键发现。", "说明意义、边界和启示。"],
        factStrategy: "摘要中的方法、结果和数字必须与原文一致。",
      }),
      recipe("reviewer-response", "审稿意见回复", "审稿回复", ["academic", "email"], "academic-paper", {
        name: "说明—回复—定位—保留意见回应法",
        summary: "逐条回应意见，说明修改、依据和稿件位置。",
        logic: "总体说明 → 逐条回复 → 修改定位 → 保留意见",
        headings: ["总体说明", "逐条回复", "修改定位", "保留意见"],
        purposes: ["简要致谢并说明修改原则。", "复述问题、给出回应和依据。", "明确页码、段落或章节位置。", "对未采纳事项给出可核查说明。"],
        factStrategy: "修改说明必须与实际稿件一致，引用应指向真实来源。",
      }),
    ]),
  });

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
