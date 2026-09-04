"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appSource = fs.readFileSync(
  path.join(__dirname, "../../gongwen_web/static/app.js"),
  "utf8",
);

function extractFunction(name) {
  const patterns = [`async function ${name}(`, `function ${name}(`];
  const start = patterns.map((pattern) => appSource.indexOf(pattern)).find((index) => index >= 0);
  assert.notEqual(start, undefined, `missing ${name}`);
  const brace = appSource.indexOf("{", start);
  let depth = 0;
  for (let index = brace; index < appSource.length; index += 1) {
    if (appSource[index] === "{") depth += 1;
    if (appSource[index] === "}") depth -= 1;
    if (depth === 0) return appSource.slice(start, index + 1);
  }
  throw new Error(`unterminated ${name}`);
}

const helpers = new Function(
  `${extractFunction("simpleHash")}
   ${extractFunction("workflowManagedMaterialId")}
   ${extractFunction("workflowStyleReferenceSourceKey")}
   return { workflowManagedMaterialId, workflowStyleReferenceSourceKey };`,
)();

test("primary material uses one project-isolated replacement slot", async () => {
  const first = await helpers.workflowManagedMaterialId("project-a", "source", "primary-material");
  const afterEdit = await helpers.workflowManagedMaterialId("project-a", "source", "primary-material");
  const otherProject = await helpers.workflowManagedMaterialId("project-b", "source", "primary-material");

  assert.equal(first, afterEdit);
  assert.notEqual(first, otherProject);
  assert.match(first, /^workspace-source-/);
  assert.ok(first.length <= 128);
});

test("article material key follows its source identity instead of editable text", async () => {
  const original = {
    id: "article-42",
    title: "原标题",
    url: "https://example.test/original",
    excerpt: "旧摘要",
    style_features: ["旧特征"],
  };
  const edited = {
    ...original,
    title: "新标题",
    url: "https://example.test/revised",
    excerpt: "新摘要",
    style_features: ["新特征"],
  };
  const originalKey = helpers.workflowStyleReferenceSourceKey(original, 0);
  const editedKey = helpers.workflowStyleReferenceSourceKey(edited, 0);
  const first = await helpers.workflowManagedMaterialId("project-a", "style", originalKey);
  const afterEdit = await helpers.workflowManagedMaterialId("project-a", "style", editedKey);
  const otherProject = await helpers.workflowManagedMaterialId("project-b", "style", originalKey);

  assert.equal(originalKey, "article-id:article-42");
  assert.equal(first, afterEdit);
  assert.notEqual(first, otherProject);
  assert.match(first, /^workspace-style-/);
});

test("article fallbacks are content-independent source slots", () => {
  assert.equal(
    helpers.workflowStyleReferenceSourceKey({ url: "https://example.test/article" }, 3),
    "article-url:https://example.test/article",
  );
  assert.equal(
    helpers.workflowStyleReferenceSourceKey({ source_name: "来源", title: "文章" }, 3),
    "article-slot:4",
  );
});

test("workspace sync detaches every retired managed id before linking active slots", () => {
  assert.match(
    appSource,
    /filter\(\(id\) => !\/\^workspace-\(\?:source\|style\)-\/\.test\(String\(id\)\)/,
  );
  assert.match(appSource, /const combined = \[\.\.\.new Set\(\[\.\.\.retained, \.\.\.ids\]/);
  assert.match(appSource, /material_id: await workflowManagedMaterialId\(projectId, "source", "primary-material"\)/);
  assert.doesNotMatch(appSource, /workflowManagedMaterialId\(projectId, "source", primary\)/);
});
