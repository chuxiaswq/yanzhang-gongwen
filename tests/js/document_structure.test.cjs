"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const catalog = require("../../gongwen_web/static/scenario_catalog.js");

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

function methodologyHarness(selectedId, recipe, custom = {}) {
  const els = {
    contentMethodology: { value: selectedId },
    customMethodologyName: { value: custom.name || "" },
    customMethodologySteps: { value: custom.steps || "" },
  };
  const ui = loadHandlers(["generationMethodologyPayload", "customMethodologyPayload"], {
    els,
    activeRecipeMethodology: () => ({
      id: `recipe-${recipe.id}`, name: recipe.name,
      summary: recipe.summary,
      headings: recipe.sections.map((section) => section.title),
      fact_strategy: recipe.fact_strategy,
    }),
  });
  return { ...ui, els };
}

test("all 19 built-in recipes leave the custom generation payload empty for canonical backend routing", () => {
  let checked = 0;
  for (const recipes of Object.values(catalog.recipes)) {
    for (const recipe of recipes) {
      const ui = methodologyHarness(`recipe-${recipe.id}`, recipe, { name: "旧自定义名", steps: "旧步骤甲\n旧步骤乙" });
      const before = JSON.stringify(ui.els);
      assert.equal(ui.generationMethodologyPayload(), null, recipe.id);
      assert.equal(ui.els.contentMethodology.value, `recipe-${recipe.id}`);
      assert.equal(JSON.stringify(ui.els), before);
      checked += 1;
    }
  }
  assert.equal(checked, 19);
});

test("other built-in methodology selections do not leak stale custom steps", () => {
  for (const selectedId of ["universal-problem-solving", "problem-analysis", ""]) {
    const ui = methodologyHarness(selectedId, catalog.recipes.gongwen[0], { steps: "旧步骤甲;旧步骤乙" });
    assert.equal(ui.generationMethodologyPayload(), null);
  }
});

test("a genuine custom methodology preserves the user's ordered steps and explanatory fields", () => {
  const ui = methodologyHarness("custom", catalog.recipes.academic[0], {
    name: "  证据比较结构  ", steps: "  问题界定\n\n概念比较； 原文证据 ;\n研究边界  ",
  });
  const before = JSON.stringify(ui.els);
  const payload = ui.generationMethodologyPayload();
  assert.equal(payload.name, "证据比较结构");
  assert.deepEqual(Array.from(payload.steps), ["问题界定", "概念比较", "原文证据", "研究边界"]);
  assert.match(payload.summary, /问题界定—概念比较—原文证据—研究边界/);
  assert.ok(payload.logic.includes("问题界定、概念比较、原文证据、研究边界"));
  assert.ok(payload.fact_strategy);
  assert.equal(JSON.stringify(ui.els), before);
  payload.steps.push("消费者自行修改");
  assert.equal(ui.generationMethodologyPayload().steps.length, 4);
});

test("an empty custom methodology stays empty while an unnamed valid one gets its explicit default", () => {
  const empty = methodologyHarness("custom", catalog.recipes.workplace[0], { steps: " \n； ; " });
  assert.equal(empty.generationMethodologyPayload(), null);
  const unnamed = methodologyHarness("custom", catalog.recipes.workplace[0], { steps: "判断\n依据" });
  assert.equal(unnamed.generationMethodologyPayload().name, "用户自定义方法论");
});

function renderHarness() {
  const documentEditor = {
    nodes: [],
    replaceChildren(fragment) { this.nodes = [...fragment.children]; },
  };
  const ui = loadHandlers(["renderContent"], {
    els: { documentEditor },
    document: {
      createDocumentFragment: () => ({ children: [], append(node) { this.children.push(node); } }),
      createElement: (tagName) => ({ tagName: tagName.toLowerCase(), textContent: "" }),
    },
  });
  return { ...ui, documentEditor };
}

test("every canonical recipe in all four scenes renders unnumbered outline headings as h2", () => {
  let checked = 0;
  for (const [scene, recipes] of Object.entries(catalog.recipes)) {
    for (const recipe of recipes) {
      const outline = recipe.sections.map((section, index) => Object.freeze({
        heading: section.title,
        content: `第 ${index + 1} 节说明已提供的材料和待确认事项。`,
      }));
      Object.freeze(outline);
      const before = JSON.stringify(outline);
      const content = outline.flatMap((section) => [section.heading, section.content]).join("\n\n");
      const ui = renderHarness();
      ui.renderContent(content, outline);
      assert.equal(ui.documentEditor.nodes.length, outline.length * 2);
      outline.forEach((section, index) => {
        const heading = ui.documentEditor.nodes[index * 2];
        const paragraph = ui.documentEditor.nodes[index * 2 + 1];
        assert.equal(heading.tagName, "h2", `${scene}/${recipe.id}/${section.heading}`);
        assert.equal(heading.textContent, section.heading);
        assert.ok(heading.id.startsWith("section-"));
        assert.equal(paragraph.tagName, "p");
        assert.equal(paragraph.textContent, section.content);
      });
      assert.equal(new Set(ui.documentEditor.nodes.filter((node) => node.tagName === "h2").map((node) => node.id)).size, outline.length);
      assert.equal(JSON.stringify(outline), before);
      checked += 1;
    }
  }
  assert.equal(checked, 19);
});

test("outline-only responses render their headings and body as distinct document blocks", () => {
  const ui = renderHarness();
  const outline = [{ heading: "研究问题", content: "明确核心问题。" }, { heading: "资料与方法", content: "方法条件由材料确认。" }];
  ui.renderContent("", outline);
  assert.deepEqual(ui.documentEditor.nodes.map((node) => [node.tagName, node.textContent]), [
    ["h2", "研究问题"], ["p", "明确核心问题。"], ["h2", "资料与方法"], ["p", "方法条件由材料确认。"],
  ]);
});

test("numbered legacy headings remain headings and ordinary numeric facts stay paragraphs", () => {
  const ui = renderHarness();
  ui.renderContent("一、总体情况\n2026年完成12项工作，后续计划另行确认。\n（二）材料范围\n现有样本占31.5%，该比例仅描述已提供数据。\n3、下一步\n18个部门已提交记录。", []);
  assert.deepEqual(ui.documentEditor.nodes.map((node) => node.tagName), ["h2", "p", "h2", "p", "h2", "p"]);
});

test("outline matching is exact rather than treating a sentence containing the heading as a heading", () => {
  const ui = renderHarness();
  ui.renderContent("证据与分歧\n证据与分歧需要逐项结合原文分析。\n原始材料含有<b>字面标记</b>。", [{ heading: "证据与分歧", content: "" }]);
  assert.deepEqual(ui.documentEditor.nodes.map((node) => node.tagName), ["h2", "p", "p"]);
  assert.equal(ui.documentEditor.nodes[2].textContent, "原始材料含有<b>字面标记</b>。");
});
