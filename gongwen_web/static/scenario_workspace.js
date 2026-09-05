(function exposeScenarioWorkspace(root, factory) {
  const catalog = root.YanzhangScenarioCatalog || (typeof require === "function" ? require("./scenario_catalog.js") : null);
  const api = factory(catalog);
  if (typeof module === "object" && module.exports) module.exports = api;
  root.YanzhangScenarioWorkspace = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createScenarioWorkspace(catalog) {
  "use strict";
  if (!catalog?.profiles || !catalog?.recipes) throw new Error("场景目录未加载");
  const clone = (value) => JSON.parse(JSON.stringify(value));

  function profile(id) { return catalog.profiles[id] || catalog.profiles.workplace; }

  function inferScenario(documentType) {
    for (const [id, recipes] of Object.entries(catalog.recipes)) {
      if (recipes.some((recipe) => recipe.content_type === documentType)) return id;
    }
    if (["通知", "请示", "报告", "函", "讲话稿", "实施方案"].includes(documentType)) return "gongwen";
    if (/论文|文献|学术|摘要|审稿/.test(documentType || "")) return "academic";
    return "workplace";
  }

  // Store each scene's input buffer independently. Changing scenes never deletes
  // source material and never carries a previous scene's evidence into a request.
  function transition({ from, to, recipeId, preferences = {}, current = {} }) {
    const next = clone(preferences);
    if (from && from !== to) next[from] = clone(current);
    const saved = from === to ? current : next[to] || {};
    const scene = profile(to);
    const knownStyle = scene.styles.some((style) => style.label === saved.reference_style);
    const style = saved.style_custom && knownStyle ? saved.reference_style
      : scene.recipe_styles?.[recipeId] || scene.default_style;
    return {
      preferences: next,
      values: {
        ...clone(saved), reference_style: style,
        style_custom: Boolean(saved.style_custom && knownStyle),
        tone: scene.tones.includes(saved.tone) ? saved.tone : scene.default_tone,
        styleReferences: Array.isArray(saved.styleReferences) && to !== "academic" ? clone(saved.styleReferences) : [],
      },
    };
  }

  function academicMaterials(academic = {}) {
    const records = Array.isArray(academic.records) ? academic.records : [];
    const evidence = Array.isArray(academic.evidence) ? academic.evidence : [];
    if (!records.length && !evidence.length) return "";
    const selected = records.slice(0, 40);
    const ids = new Set(selected.map((record) => String(record.id)));
    const excerpts = evidence.filter((item) => ids.has(String(item.record_id)) && String(item.text || "").trim()).slice(0, 40);
    const metadata = selected.map((record) => `[文献 ${record.id}] ${record.title || "标题待补"}；年份：${record.issued_year || record.year || "待核"}；DOI：${record.doi || "未提供"}`);
    const quotes = excerpts.map((item) => {
      const location = [item.section, item.page_start != null ? `页 ${item.page_start}${item.page_end != null ? `–${item.page_end}` : ""}` : "", item.paragraph_index != null ? `段 ${item.paragraph_index}` : "", item.char_start != null ? `字符 ${item.char_start}${item.char_end != null ? `–${item.char_end}` : ""}` : ""].filter(Boolean).join("；");
      const locator = typeof item.locator === "string" ? item.locator : JSON.stringify(item.locator || item.location || "");
      return `[证据 ${item.id}｜文献 ${item.record_id}] ${String(item.text || "").slice(0, 1800)}\n定位：${location || (locator !== '""' ? locator : "待核")}`;
    });
    return [
      "【已导入学术材料包】元数据仅用于识别文献，不证明研究结论；正文主张须依据下列原文证据。引用保留来源 ID，不凭标题推断结果。",
      ...metadata, ...quotes,
      !excerpts.length ? "【待补原文证据】尚未加入可定位的原文片段；仅输出研究结构和待核问题，不生成文献发现或研究结果。" : "",
      records.length > selected.length || evidence.length > excerpts.length ? `本次材料包列出 ${selected.length}/${records.length} 条文献及 ${excerpts.length}/${evidence.length} 条证据，其余内容未参与本次生成。` : "",
    ].filter(Boolean).join("\n\n");
  }

  function expressionCandidates(packId, focus, { topic, goal, audience, headings = [] }, count = 5) {
    const t = String(topic || "当前主题").replace(/[，。！？；:：]+$/g, "");
    const g = String(goal || "明确问题与下一步");
    const a = String(audience || "目标读者");
    const common = {
      title: [`${t}：问题、证据与行动`, `${t}的关键问题与改进路径`, `从现状到下一步：${t}`, `${t}｜核心判断与行动建议`, `${t}：范围、重点与待确认事项`],
      opening: [`本文围绕${t}展开，先说明核心判断，再列出支撑材料。`, `面向${a}，这份材料重点回答${g}。`, `${t}需要先明确范围，再区分已知事实与待确认问题。`, `关于${t}，以下按结论、依据和下一步组织信息。`, `讨论${t}，应把可核查的事实放在判断之前。`],
      topic_sentence: ["先明确结论，才能判断哪些材料真正相关。", "已有记录应与推测分开，避免把计划写成成果。", "关键分歧需要通过证据比较，而非重复立场来解决。", "下一步行动应对应尚未解决的具体问题。", "本段先说明判断，再列出依据与适用边界。"],
      section_heading: headings,
    };
    const specialized = {
      workplace: {
        title: [`${t}｜结论与待决策事项`, `${t}：进展、风险与所需支持`, `关于${t}的行动建议`, `${t}方案比较与推荐路径`, `${t}｜本次沟通需要确认的三件事`],
        opening: [`这份材料希望就${t}形成明确决定，所需支持和待确认事项列在前面。`, `关于${t}，请先关注结论、影响和下一步安排。`, `为便于${a}快速判断，以下仅保留与${g}直接相关的信息。`, `${t}的进展以实际工作记录为准，未确认承诺单独标注。`, `本次沟通的重点不是罗列过程，而是明确${t}的结果与阻塞。`],
        topic_sentence: ["已完成事项应以交付物和验收记录说明，而不是以投入时长替代成果。", "当前风险需要明确影响范围及所需支持。", "方案比较应在相同成本、收益和时间边界下进行。", "待办事项应写清动作、负责人和截止时间，缺失项标为待确认。", "本次需要确认的是决策选项，而非再次重复背景。"],
      },
      media: {
        title: [`${t}：发生了什么，为什么值得关注`, `读懂${t}的几个关键问题`, `${t}｜事实、背景与影响`, `从一个问题看${t}`, `${t}：哪些已确认，哪些仍待核实`],
        opening: [`${t}有哪些已确认事实？本文先交代信息来源，再说明背景。`, `理解${t}，需要区分事件事实、各方观点和作者判断。`, `对${a}而言，${t}最值得关注的是与自身相关的具体影响。`, `围绕${t}，下面按事件、背景和影响梳理信息。`, `本文以已确认材料为边界，回应关于${t}的主要问题。`],
        topic_sentence: ["事件背景决定了读者如何理解眼前的信息。", "引语应保留说话者与出处，避免把转述当作原话。", "标题中的判断应能在正文事实中找到对应依据。", "具体场景可以帮助理解问题，但不能替代证据。", "收束应回到读者关切，不添加未经证实的效果承诺。"],
      },
      academic: {
        title: [`${t}：研究进展、证据分歧与未来方向`, `${t}的概念框架与研究路径`, `${t}：基于现有文献的主题分析`, `${t}研究的证据边界与待解问题`, `${t}：研究问题、方法与贡献边界`],
        opening: [`本文围绕${t}界定研究范围，并区分既有文献结论与待检验假设。`, `对${t}的讨论应首先澄清核心概念、材料范围与证据标准。`, `本文拟回答${g}；相关论断仅在具备原文依据时展开。`, `${t}的文献整理以主题、方法和证据强度为比较维度，而非逐篇罗列。`, `研究${t}需要说明材料纳入范围，并报告证据不足之处。`],
        topic_sentence: ["概念口径的差异可能影响研究结论的可比性，需要先进行界定。", "结论是否一致，应结合研究设计、样本与测量方法共同判断。", "相关关系与因果解释应明确区分，避免超出原文证据作推断。", "研究空白应由文献比较推导，而非将材料不足直接表述为学界空白。", "本节仅在可定位的原文证据范围内展开，缺失引文暂标为待补。"],
      },
    };
    const values = specialized[packId]?.[focus] || common[focus] || common.title;
    const unique = [...new Set(values.filter(Boolean))];
    return unique.slice(0, Math.max(1, Math.min(8, count)));
  }

  return Object.freeze({ profile, inferScenario, transition, academicMaterials, expressionCandidates });
});
