"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const validators = require("../../gongwen_web/static/response_validators.js");

function claim(id, requiresCitation = true) {
  return { id, text: `论断 ${id}`, requires_citation: requiresCitation };
}

function link(overrides = {}) {
  return {
    id: "link-1",
    claim_id: "claim-1",
    record_id: "record-1",
    evidence_id: "evidence-1",
    relation: "supports",
    support_score: 0.75,
    status: "verified",
    issues: [],
    verified_at: "2026-09-04T00:00:00Z",
    ...overrides,
  };
}

function citationAudit(overrides = {}) {
  return {
    links: [link()],
    comments: [],
    required_claim_count: 1,
    supported_claim_count: 1,
    coverage: 1,
    ...overrides,
  };
}

function reviewComment(overrides = {}) {
  return {
    id: "comment-1",
    category: "citation",
    severity: "error",
    message: "引用缺失",
    recommendation: "补充证据。",
    location: "",
    claim_id: "claim-1",
    record_id: null,
    evidence_id: null,
    resolved: false,
    ...overrides,
  };
}

test("citation audit ties counts and coverage to verified supporting links", () => {
  const claims = [claim("claim-1"), claim("claim-optional", false)];
  assert.equal(validators.validateCitationAudit(citationAudit(), claims), true);
  assert.equal(validators.validateCitationAudit(citationAudit({ required_claim_count: 0 }), claims), false);
  assert.equal(validators.validateCitationAudit(citationAudit({ supported_claim_count: 0 }), claims), false);
  assert.equal(validators.validateCitationAudit(citationAudit({ coverage: 0 }), claims), false);
  assert.equal(validators.validateCitationAudit(citationAudit({
    links: [link({ status: "needs-review" })],
  }), claims), false);
  assert.equal(validators.validateCitationAudit(citationAudit({
    links: [link({ claim_id: "claim-from-another-request" })],
  }), claims), false);
});

test("zero required claims use full coverage without inventing support", () => {
  const claims = [claim("claim-optional", false)];
  const audit = citationAudit({
    links: [],
    required_claim_count: 0,
    supported_claim_count: 0,
    coverage: 1,
  });
  assert.equal(validators.validateCitationAudit(audit, claims), true);
  assert.equal(validators.validateCitationAudit({ ...audit, coverage: 0 }, claims), false);
});

test("integrity pass flag agrees with complete citation audit and error comments", () => {
  const claims = [claim("claim-1")];
  const audit = citationAudit();
  assert.equal(validators.validateIntegrityReview({ citation_audit: audit, comments: [], passed: true }, claims), true);
  const errorComment = reviewComment();
  const auditWithError = { ...audit, comments: [errorComment] };
  assert.equal(validators.validateIntegrityReview({ citation_audit: auditWithError, comments: [errorComment], passed: false }, claims), true);
  assert.equal(validators.validateIntegrityReview({ citation_audit: auditWithError, comments: [errorComment], passed: true }, claims), false);
  assert.equal(validators.validateIntegrityReview({ citation_audit: auditWithError, comments: [], passed: true }, claims), false);
  assert.equal(validators.validateIntegrityReview({
    citation_audit: auditWithError,
    comments: [{ ...errorComment, severity: "warning" }],
    passed: true,
  }, claims), false);
  assert.equal(validators.validateIntegrityReview({ citation_audit: audit, comments: [], passed: false }, claims), false);
});

function reviewEnvelope(overrides = {}) {
  const base = {
    checks: ["structure"],
    review_dimensions: ["logic", "format"],
    effective_mode: "local",
    resolved_route: { profile: { id: "local-deterministic" } },
    model_issue_count: 0,
    review: {
      asset_id: "asset-1",
      overall_score: 85,
      passed: true,
      dimensions: [
        { dimension: "logic", label: "逻辑与结构", score: 90, issue_count: 1, summary: "发现 1 项可处理问题。" },
        { dimension: "format", label: "格式与交付", score: 80, issue_count: 0, summary: "检查通过。" },
      ],
      issues: [{
        id: "issue-1",
        dimension: "logic",
        severity: "warning",
        block_id: "block-1",
        message: "段落衔接可加强。",
        suggestion: "补充承接句。",
      }],
      metrics: {
        character_count: 100,
        block_count: 4,
        claim_like_count: 2,
        cited_claim_like_count: 1,
        evidence_coverage: 50,
      },
    },
  };
  return { ...base, ...overrides };
}

test("project review requires the complete internally consistent envelope", () => {
  const options = { assetId: "asset-1", checks: ["structure"], dimensions: ["logic", "format"] };
  const valid = reviewEnvelope();
  assert.equal(validators.validateProjectReviewEnvelope(valid, options), true);
  assert.equal(validators.validateProjectReviewEnvelope({ review: { overall_score: 80 } }, options), false);
  assert.equal(validators.validateProjectReviewEnvelope({ ...valid, review: { ...valid.review, asset_id: "asset-2" } }, options), false);
  assert.equal(validators.validateProjectReviewEnvelope({ ...valid, review: { ...valid.review, metrics: {} } }, options), false);
  assert.equal(validators.validateProjectReviewEnvelope({
    ...valid,
    review: { ...valid.review, dimensions: valid.review.dimensions.map((item) => ({ ...item, issue_count: 0 })) },
  }, options), false);
  assert.equal(validators.validateProjectReviewEnvelope({ ...valid, review: { ...valid.review, overall_score: 86 } }, options), false);
  assert.equal(validators.validateProjectReviewEnvelope({ ...valid, review: { ...valid.review, passed: false } }, options), false);
  assert.equal(validators.validateProjectReviewEnvelope({
    ...valid,
    review_dimensions: ["format", "logic"],
    review: { ...valid.review, dimensions: [...valid.review.dimensions].reverse() },
  }, options), false);
  assert.equal(validators.validateProjectReviewEnvelope({
    ...valid,
    review: { ...valid.review, metrics: { ...valid.review.metrics, evidence_coverage: 100 } },
  }, options), false);
});

test("page and variant validators reject ambiguous successful responses", () => {
  const page = { items: [{ id: "one" }], count: 1, total: 2, limit: 1, offset: 0, has_more: true };
  assert.equal(validators.validatePage(page, { expectedOffset: 0, expectedLimit: 1 }), true);
  assert.equal(validators.validatePage({ ...page, has_more: false }, { expectedOffset: 0 }), false);
  assert.equal(validators.validatePage({ ...page, total: 0 }, { expectedOffset: 0 }), false);

  const variant = {
    id: "variant-1",
    channel: "email",
    title: "邮件版",
    parent_asset_id: "asset-1",
    blocks: [{ id: "block-1", kind: "paragraph", order: 0, text: "正文" }],
  };
  assert.equal(validators.validateVariantAsset(variant, {
    expectedChannel: "email",
    expectedParentAssetId: "asset-1",
  }), true);
  assert.equal(validators.validateVariantAsset({ ...variant, id: "" }, {}), false);
});

test("pagination contract covers 101 and 201 item boundaries without silent gaps", () => {
  const first100 = { items: Array.from({ length: 100 }, (_, index) => ({ id: `i-${index}` })), count: 100, total: 201, limit: 100, offset: 0, has_more: true };
  const second100 = { items: Array.from({ length: 100 }, (_, index) => ({ id: `i-${index + 100}` })), count: 100, total: 201, limit: 100, offset: 100, has_more: true };
  const finalOne = { items: [{ id: "i-200" }], count: 1, total: 201, limit: 100, offset: 200, has_more: false };
  assert.equal(validators.validatePage(first100, { expectedOffset: 0, expectedLimit: 100 }), true);
  assert.equal(validators.validatePage(second100, { expectedOffset: 100, expectedLimit: 100, expectedTotal: 201 }), true);
  assert.equal(validators.validatePage(finalOne, { expectedOffset: 200, expectedLimit: 100, expectedTotal: 201 }), true);
  assert.equal(validators.validatePage({ ...second100, total: 200 }, { expectedOffset: 100, expectedLimit: 100, expectedTotal: 201 }), false);
  assert.equal(validators.validatePage({ ...finalOne, has_more: true }, { expectedOffset: 200, expectedLimit: 100 }), false);
});

test("academic matrix, outline and abstract validators reject malformed 2xx bodies", () => {
  const matrix = {
    id: "matrix-1",
    record_ids: ["record-1"],
    themes: [],
    rows: [{ record_id: "record-1", citation_label: "作者，2026", research_object: "", methods: [], findings: [], limitations: [], themes: [], evidence_ids: ["evidence-1"] }],
  };
  const matrixOptions = { recordIds: ["record-1"], evidenceIds: ["evidence-1"] };
  assert.equal(validators.validateAcademicMatrix(matrix, matrixOptions), true);
  assert.equal(validators.validateAcademicMatrix({ ...matrix, rows: [{}] }, matrixOptions), false);
  assert.equal(validators.validateAcademicMatrix({ ...matrix, record_ids: [] }, matrixOptions), false);

  const outline = {
    title: "研究提纲",
    record_ids: ["record-1"],
    sections: [{ heading: "一、问题提出", purpose: "界定问题", questions: [], record_ids: ["record-1"], evidence_ids: [] }],
  };
  assert.equal(validators.validateAcademicOutline(outline, { recordIds: ["record-1"] }), true);
  assert.equal(validators.validateAcademicOutline({ title: "只有标题", record_ids: [], sections: [] }, { recordIds: [] }), false);

  const abstract = { text: "摘要正文", record_ids: ["record-1"], claim_ids: ["claim-1"], placeholders: [] };
  assert.equal(validators.validateAcademicAbstract(abstract, { recordIds: ["record-1"], claimIds: ["claim-1"] }), true);
  assert.equal(validators.validateAcademicAbstract({ ...abstract, text: "" }, { recordIds: ["record-1"], claimIds: ["claim-1"] }), false);
  assert.equal(validators.validateAcademicAbstract({ ...abstract, claim_ids: ["foreign"] }, { recordIds: ["record-1"], claimIds: ["claim-1"] }), false);
});

test("variant contract never fabricates lineage for a successful response", () => {
  const base = {
    id: "variant-1",
    channel: "email",
    title: "邮件版",
    parent_asset_id: "asset-1",
    blocks: [{ id: "block-1", kind: "paragraph", order: 0, text: "正文" }],
  };
  const expected = { expectedChannel: "email", expectedParentAssetId: "asset-1" };
  for (const key of ["id", "channel", "title", "parent_asset_id", "blocks"]) {
    const malformed = { ...base };
    delete malformed[key];
    assert.equal(validators.validateVariantAsset(malformed, expected), false, key);
  }
  assert.equal(validators.validateVariantAsset({ ...base, channel: "web" }, expected), false);
  assert.equal(validators.validateVariantAsset({ ...base, parent_asset_id: "asset-2" }, expected), false);
});
