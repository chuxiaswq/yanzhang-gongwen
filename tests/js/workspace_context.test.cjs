"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const context = require("../../gongwen_web/static/workspace_context.js");

test("every recipe resolves to one coherent writing context", () => {
  const seen = new Set();
  const actual = [];
  const byContentType = {};
  for (const [packId, recipes] of Object.entries(context.RECIPE_CATALOG)) {
    for (const recipe of recipes) {
      const [recipeId, , documentType, channels, profile] = recipe;
      const resolved = context.resolveWorkspaceContext({
        packId,
        recipeId,
        contentType: context.DEFAULT_CONTENT_TYPE[packId],
        channel: "incompatible-channel",
        documentType: "旧文种",
        academicTaskType: "",
      }, "recipe");
      assert.equal(resolved.scenarioPackId, packId);
      assert.equal(resolved.recipeId, recipeId);
      assert.equal(resolved.documentType, documentType);
      assert.equal(resolved.channel, channels[0]);
      assert.equal(resolved.contentType, profile.contentType);
      assert.deepEqual([...resolved.headings], [...profile.methodology.headings]);
      assert.ok(resolved.methodology.name);
      assert.ok(resolved.methodology.fact_strategy);
      assert.equal(seen.has(recipeId), false, `duplicate recipe id: ${recipeId}`);
      seen.add(recipeId);
      (byContentType[profile.contentType] ||= []).push(recipeId);
      actual.push([recipeId, packId, documentType, [...channels], [...profile.methodology.headings]]);
    }
  }
  assert.deepEqual(actual, [
    ["work-summary", "gongwen", "工作总结", ["document"], ["总体情况", "主要成效", "问题不足", "下一步安排"]],
    ["briefing-material", "gongwen", "汇报材料", ["document", "presentation"], ["工作进展", "亮点成效", "困难问题", "工作计划"]],
    ["leadership-speech", "gongwen", "讲话稿", ["document"], ["提高站位，凝聚思想共识", "突出重点，推动任务落实", "压实责任，确保取得实效"]],
    ["research-report", "gongwen", "调研报告", ["document"], ["调研概况", "现状与成效", "问题与原因", "对策建议"]],
    ["implementation-plan", "gongwen", "实施方案", ["document"], ["总体要求", "工作目标", "重点举措", "实施步骤", "保障措施"]],
    ["meeting-minutes", "gongwen", "会议纪要", ["meeting", "document"], ["会议情况", "议定事项", "责任分工", "落实要求"]],
    ["work-email", "workplace", "邮件", ["email"], ["邮件主题", "背景与结论", "必要信息", "下一步"]],
    ["weekly-report", "workplace", "周报", ["document", "email"], ["本周完成", "进行中", "风险与协同", "下周计划"]],
    ["business-proposal", "workplace", "业务方案", ["document", "presentation"], ["问题与机会", "目标与原则", "方案设计", "预期价值", "风险与推进"]],
    ["meeting-followup", "workplace", "会议跟办", ["meeting", "email"], ["会议结论", "行动项", "依赖与风险", "待确认事项"]],
    ["presentation-outline", "workplace", "PPT提纲", ["presentation"], ["核心结论", "叙事主线", "逐页提纲", "收束与行动"]],
    ["press-release", "media", "新闻稿", ["web", "document"], ["标题", "导语", "主体", "背景"]],
    ["wechat-article", "media", "公众号文章", ["web"], ["标题与开场", "问题场景", "核心内容", "总结与行动"]],
    ["social-post", "media", "社交媒体文案", ["social"], ["开场", "正文", "收束"]],
    ["short-video-script", "media", "短视频脚本", ["social"], ["开场钩子", "内容节拍", "关键转折", "行动提示"]],
    ["literature-review", "academic", "文献综述", ["academic", "document"], ["问题与范围", "主题脉络", "证据与分歧", "研究空白"]],
    ["research-outline", "academic", "研究提纲", ["academic", "document"], ["研究问题", "分析框架", "资料与方法", "章节结构"]],
    ["research-abstract", "academic", "摘要", ["academic"], ["背景与目的", "方法", "结果", "结论"]],
    ["reviewer-response", "academic", "审稿回复", ["academic", "email"], ["总体说明", "逐条回复", "修改定位", "保留意见"]],
  ]);
  assert.deepEqual(byContentType, {
    "official-document": ["work-summary", "briefing-material", "implementation-plan", "meeting-minutes"],
    "leadership-speech": ["leadership-speech"],
    "research-report": ["research-report"],
    "general-writing": ["work-email", "weekly-report", "business-proposal", "meeting-followup", "presentation-outline", "wechat-article", "social-post", "short-video-script"],
    "news-release": ["press-release"],
    "academic-paper": ["literature-review", "research-outline", "research-abstract", "reviewer-response"],
  });
});

test("restore makes the selected recipe authoritative over stale family metadata", () => {
  const resolved = context.resolveWorkspaceContext({
    contentType: "research-report",
    packId: "gongwen",
    recipeId: "work-summary",
    channel: "document",
    documentType: "工作总结",
    academicTaskType: "",
  }, "restore");
  assert.equal(resolved.contentType, "official-document");
  assert.equal(resolved.documentType, "工作总结");
});

test("academic content, pack, recipe, document type and task type reconcile bidirectionally", () => {
  const starting = {
    contentType: "academic-paper",
    packId: "gongwen",
    recipeId: "work-summary",
    channel: "document",
    documentType: "工作总结",
    academicTaskType: "literature-review",
  };
  const fromContent = context.resolveWorkspaceContext(starting, "content_type");
  assert.deepEqual({
    contentType: fromContent.contentType,
    packId: fromContent.scenarioPackId,
    recipeId: fromContent.recipeId,
    channel: fromContent.channel,
    documentType: fromContent.documentType,
    taskType: fromContent.academicTaskType,
    headings: [...fromContent.headings],
  }, {
    contentType: "academic-paper",
    packId: "academic",
    recipeId: "literature-review",
    channel: "academic",
    documentType: "文献综述",
    taskType: "literature-review",
    headings: ["问题与范围", "主题脉络", "证据与分歧", "研究空白"],
  });

  for (const [source, overrides] of [
    ["scenario_pack", { packId: "academic" }],
    ["recipe", { packId: "academic", recipeId: "literature-review" }],
    ["document_type", { documentType: "文献综述" }],
    ["academic_task", { academicTaskType: "literature-review" }],
  ]) {
    const resolved = context.resolveWorkspaceContext({ ...starting, ...overrides }, source);
    assert.equal(resolved.scenarioPackId, "academic", source);
    assert.equal(resolved.recipeId, "literature-review", source);
    assert.equal(resolved.contentType, "academic-paper", source);
    assert.equal(resolved.documentType, "文献综述", source);
    assert.equal(resolved.academicTaskType, "literature-review", source);
  }
});

test("standalone legacy documents keep their original document type", () => {
  for (const documentType of ["通知", "请示", "报告", "函"]) {
    const resolved = context.resolveStandaloneDocumentContext({
      contentType: "official-document",
      packId: "gongwen",
      recipeId: "implementation-plan",
      channel: "document",
      documentType,
      academicTaskType: "literature-review",
    });
    assert.equal(resolved.documentType, documentType);
    assert.equal(resolved.scenarioPackId, "gongwen");
    assert.equal(resolved.recipeId, "implementation-plan");
  }

  const known = context.resolveStandaloneDocumentContext({
    contentType: "official-document",
    packId: "gongwen",
    recipeId: "implementation-plan",
    channel: "document",
    documentType: "工作总结",
    academicTaskType: "literature-review",
  });
  assert.equal(known.documentType, "工作总结");
  assert.equal(known.recipeId, "work-summary");
});

test("each academic task selects the matching recipe and structure", () => {
  const expected = {
    "literature-review": ["literature-review", ["问题与范围", "主题脉络", "证据与分歧", "研究空白"]],
    "research-outline": ["research-outline", ["研究问题", "分析框架", "资料与方法", "章节结构"]],
    abstract: ["research-abstract", ["背景与目的", "方法", "结果", "结论"]],
    rebuttal: ["reviewer-response", ["总体说明", "逐条回复", "修改定位", "保留意见"]],
  };
  for (const [taskType, [recipeId, headings]] of Object.entries(expected)) {
    const resolved = context.resolveWorkspaceContext({
      contentType: "official-document",
      packId: "gongwen",
      recipeId: "work-summary",
      channel: "document",
      documentType: "工作总结",
      academicTaskType: taskType,
    }, "academic_task");
    assert.equal(resolved.recipeId, recipeId);
    assert.equal(resolved.channel, "academic");
    assert.deepEqual([...resolved.headings], headings);
  }
});

test("brief and generation signatures include every fact and style input", () => {
  const base = {
    payload: { title: "数字化转型", goal: "总结成效" },
    contentTypeFamily: "official-document",
    deadline: "2026-09-30",
    documentType: "工作总结",
    referenceStyle: "权威媒体综合写法",
    contentMethodologyId: "recipe-work-summary",
    customMethodology: null,
    selectedTitle: "标题甲",
    titleFormulaIds: ["summary-standard"],
    customTitleFormula: null,
    factLock: true,
    materialsHash: "facts-a",
    styleReferences: [{ id: "ref-a", source_name: "求是网", title: "文章甲", excerpt: "写法甲", style_features: ["递进"] }],
    workspaceMaterialIds: ["material-a"],
  };
  const signature = context.briefBindingSignature(base);
  for (const changed of [
    { materialsHash: "facts-b" },
    { referenceStyle: "简洁新闻写法" },
    { factLock: false },
    { styleReferences: [{ ...base.styleReferences[0], excerpt: "写法乙" }] },
    { customMethodology: { steps: ["甲", "乙"] } },
    { titleFormulaIds: ["generic-elements"] },
  ]) {
    assert.notEqual(context.briefBindingSignature({ ...base, ...changed }), signature);
  }
  const generation = context.generationInputSignature({
    projectId: "project-a",
    briefBindingHash: signature,
    document: { title: "标题甲", content_hash: "draft-a" },
  });
  assert.notEqual(context.generationInputSignature({
    projectId: "project-a",
    briefBindingHash: context.briefBindingSignature({ ...base, materialsHash: "facts-b" }),
    document: { title: "标题甲", content_hash: "draft-a" },
  }), generation);
});

test("delayed operations, assets and document saves stay bound to their snapshots", () => {
  const operation = { projectId: "project-a", projectSerial: 7, inputHash: "input-a" };
  assert.equal(context.operationMatches(operation, { ...operation }), true);
  assert.equal(context.operationMatches(operation, { ...operation, inputHash: "input-b" }), false);
  assert.equal(context.operationMatches(operation, { ...operation, projectId: "project-b" }), false);

  const asset = { id: "asset-a", brief_id: "brief-a", project_id: "project-a" };
  assert.equal(context.assetMatchesBinding(asset, {
    assetId: "asset-a", projectId: "project-a", briefId: "brief-a", requireBriefId: true,
  }), true);
  assert.equal(context.assetMatchesBinding(asset, {
    assetId: "asset-a", projectId: "project-a", briefId: "brief-b", requireBriefId: true,
  }), false);
  assert.equal(context.assetMatchesBinding({ id: "asset-a" }, { requireBriefId: true }), false);

  const save = {
    documentId: "document-a", documentVersion: 2, editorHash: "editor-a",
    projectId: "project-a", projectSerial: 7,
  };
  assert.equal(context.documentSaveResponseMatches(save, { ...save }, { id: "document-a" }), true);
  assert.equal(context.documentSaveResponseMatches(save, { ...save, editorHash: "editor-b" }, { id: "document-a" }), false);
  assert.equal(context.documentSaveResponseMatches(save, { ...save }, { id: "document-b" }), false);
});

test("methodology responses are accepted only for the active project and context", () => {
  const request = {
    requestSerial: 4,
    projectSerial: 9,
    projectId: "project-b",
    documentType: "文献综述",
    contextSignature: "academic/literature-review",
  };
  assert.equal(context.catalogRequestMatches(request, { ...request }), true);
  for (const changed of [
    { requestSerial: 5 },
    { projectSerial: 10 },
    { projectId: "project-a" },
    { documentType: "实施方案" },
    { contextSignature: "gongwen/implementation-plan" },
  ]) assert.equal(context.catalogRequestMatches(request, { ...request, ...changed }), false);
});
