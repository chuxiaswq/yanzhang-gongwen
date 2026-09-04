(function exposeYanzhangResponseValidators(root, factory) {
  "use strict";

  const validators = factory();
  if (typeof module === "object" && module.exports) module.exports = validators;
  if (root) root.YanzhangResponseValidators = validators;
})(typeof globalThis === "object" ? globalThis : this, function createValidators() {
  "use strict";

  const REVIEW_DIMENSIONS = new Set([
    "evidence", "logic", "clarity", "audience_tone", "language", "format",
  ]);
  const REVIEW_SEVERITIES = new Set(["info", "warning", "error"]);
  const REVIEW_CATEGORIES = new Set([
    "citation", "metadata", "evidence", "consistency", "integrity", "style", "method",
  ]);
  const LINK_RELATIONS = new Set(["supports", "contradicts", "context"]);
  const LINK_STATUSES = new Set(["verified", "needs-review", "invalid"]);

  function isObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function isFiniteNumber(value, minimum, maximum) {
    return typeof value === "number" && Number.isFinite(value)
      && value >= minimum && value <= maximum;
  }

  function isInteger(value, minimum, maximum = Number.MAX_SAFE_INTEGER) {
    return Number.isInteger(value) && value >= minimum && value <= maximum;
  }

  function hasText(value) {
    return typeof value === "string" && Boolean(value.trim());
  }

  function sameSequence(left, right) {
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length
      && left.every((value, index) => value === right[index]);
  }

  function sameMembers(left, right) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) return false;
    const leftSet = new Set(left);
    const rightSet = new Set(right);
    return leftSet.size === left.length && rightSet.size === right.length
      && [...leftSet].every((value) => rightSet.has(value));
  }

  function validateReviewComment(comment) {
    if (!isObject(comment) || !hasText(comment.id) || !REVIEW_CATEGORIES.has(comment.category)
      || !REVIEW_SEVERITIES.has(comment.severity) || !hasText(comment.message)
      || typeof comment.recommendation !== "string" || typeof comment.location !== "string"
      || typeof comment.resolved !== "boolean") return false;
    return ["claim_id", "record_id", "evidence_id"].every((key) => comment[key] === null
      || comment[key] === undefined || hasText(comment[key]));
  }

  function validateCitationAudit(audit, claims) {
    if (!isObject(audit) || !Array.isArray(claims) || !Array.isArray(audit.links)
      || !Array.isArray(audit.comments)) return false;

    const claimIds = new Set();
    const requiredClaimIds = new Set();
    for (const claim of claims) {
      if (!isObject(claim) || !hasText(claim.id) || !hasText(claim.text)
        || claimIds.has(claim.id)) return false;
      claimIds.add(claim.id);
      if (claim.requires_citation !== false) requiredClaimIds.add(claim.id);
    }

    const supportedClaimIds = new Set();
    const linkIds = new Set();
    for (const link of audit.links) {
      if (!isObject(link) || !hasText(link.id) || linkIds.has(link.id)
        || !hasText(link.claim_id) || !claimIds.has(link.claim_id)
        || !hasText(link.record_id) || !hasText(link.evidence_id)
        || !LINK_RELATIONS.has(link.relation) || !LINK_STATUSES.has(link.status)
        || !isFiniteNumber(link.support_score, 0, 1) || !Array.isArray(link.issues)) return false;
      if (!link.issues.every((issue) => typeof issue === "string")) return false;
      linkIds.add(link.id);
      if (link.status === "verified" && link.relation === "supports"
        && requiredClaimIds.has(link.claim_id)) supportedClaimIds.add(link.claim_id);
    }

    if (!audit.comments.every(validateReviewComment)) return false;
    if (!isInteger(audit.required_claim_count, 0)
      || audit.required_claim_count !== requiredClaimIds.size) return false;
    if (!isInteger(audit.supported_claim_count, 0)
      || audit.supported_claim_count !== supportedClaimIds.size) return false;
    if (!isFiniteNumber(audit.coverage, 0, 1)) return false;
    const expectedCoverage = requiredClaimIds.size
      ? supportedClaimIds.size / requiredClaimIds.size
      : 1;
    return Math.abs(audit.coverage - expectedCoverage) <= 0.0001;
  }

  function validateIntegrityReview(review, claims) {
    if (!isObject(review) || typeof review.passed !== "boolean"
      || !Array.isArray(review.comments)
      || !validateCitationAudit(review.citation_audit, claims)) return false;
    if (!review.comments.every(validateReviewComment)) return false;
    const outerComments = new Map(review.comments.map((comment) => [comment.id, comment]));
    const sharedFields = [
      "category", "severity", "message", "recommendation", "location",
      "claim_id", "record_id", "evidence_id", "resolved",
    ];
    if (!review.citation_audit.comments.every((comment) => {
      const outer = outerComments.get(comment.id);
      return outer && sharedFields.every((field) => outer[field] === comment[field]);
    })) return false;
    const hasError = review.comments.some((comment) => comment.severity === "error");
    const expectedPassed = !hasError;
    return review.passed === expectedPassed;
  }

  function validateProjectReviewEnvelope(payload, options) {
    const expected = isObject(options) ? options : {};
    if (!isObject(payload) || !isObject(payload.review)) return false;
    const review = payload.review;
    if (!hasText(review.asset_id) || (hasText(expected.assetId) && review.asset_id !== expected.assetId)
      || !isInteger(review.overall_score, 0, 100) || typeof review.passed !== "boolean"
      || !Array.isArray(review.dimensions) || !review.dimensions.length
      || !Array.isArray(review.issues) || !isObject(review.metrics)) return false;

    if (!Array.isArray(payload.review_dimensions) || !payload.review_dimensions.length
      || !payload.review_dimensions.every((dimension) => REVIEW_DIMENSIONS.has(dimension))) return false;
    if (new Set(payload.review_dimensions).size !== payload.review_dimensions.length) return false;
    if (Array.isArray(expected.dimensions)
      && !sameSequence(payload.review_dimensions, expected.dimensions)) return false;
    if (!Array.isArray(payload.checks) || !payload.checks.every(hasText)) return false;
    if (Array.isArray(expected.checks) && !sameSequence(payload.checks, expected.checks)) return false;

    const dimensionIds = [];
    for (const dimension of review.dimensions) {
      if (!isObject(dimension) || !REVIEW_DIMENSIONS.has(dimension.dimension)
        || !payload.review_dimensions.includes(dimension.dimension)
        || !hasText(dimension.label) || !isInteger(dimension.score, 0, 100)
        || !isInteger(dimension.issue_count, 0) || !hasText(dimension.summary)) return false;
      dimensionIds.push(dimension.dimension);
    }
    if (!sameSequence(dimensionIds, payload.review_dimensions)) return false;

    const issueCounts = new Map(payload.review_dimensions.map((dimension) => [dimension, 0]));
    const issueIds = new Set();
    for (const issue of review.issues) {
      if (!isObject(issue) || !hasText(issue.id) || issueIds.has(issue.id)
        || !payload.review_dimensions.includes(issue.dimension)
        || !REVIEW_SEVERITIES.has(issue.severity) || !hasText(issue.message)
        || !hasText(issue.suggestion)) return false;
      if (issue.block_id !== null && issue.block_id !== undefined && !hasText(issue.block_id)) return false;
      issueIds.add(issue.id);
      issueCounts.set(issue.dimension, issueCounts.get(issue.dimension) + 1);
    }
    if (!review.dimensions.every((dimension) => dimension.issue_count === issueCounts.get(dimension.dimension))) return false;

    for (const metric of ["character_count", "block_count", "claim_like_count", "cited_claim_like_count", "evidence_coverage"]) {
      if (!isInteger(review.metrics[metric], 0, metric === "evidence_coverage" ? 100 : Number.MAX_SAFE_INTEGER)) return false;
    }
    if (review.metrics.cited_claim_like_count > review.metrics.claim_like_count) return false;
    const expectedCoverage = review.metrics.claim_like_count === 0
      ? 100
      : Math.round(review.metrics.cited_claim_like_count * 100 / review.metrics.claim_like_count);
    if (review.metrics.evidence_coverage !== expectedCoverage) return false;
    if (!new Set(["live", "local"]).has(payload.effective_mode)
      || !isObject(payload.resolved_route) || !isInteger(payload.model_issue_count, 0)) return false;
    const score = Math.round(review.dimensions.reduce((sum, dimension) => sum + dimension.score, 0) / review.dimensions.length);
    const expectedPassed = score >= 80 && !review.issues.some((issue) => issue.severity === "error");
    return review.overall_score === score && review.passed === expectedPassed;
  }

  function validatePage(response, options) {
    const expected = isObject(options) ? options : {};
    if (!isObject(response) || !Array.isArray(response.items)
      || !isInteger(response.offset, 0) || !isInteger(response.limit, 1)
      || !isInteger(response.count, 0) || !isInteger(response.total, 0)
      || typeof response.has_more !== "boolean") return false;
    if (response.count !== response.items.length || response.count > response.limit
      || response.total < response.offset + response.count
      || response.has_more !== (response.offset + response.count < response.total)) return false;
    if (Number.isInteger(expected.expectedOffset) && response.offset !== expected.expectedOffset) return false;
    if (Number.isInteger(expected.expectedLimit) && response.limit !== expected.expectedLimit) return false;
    if (Number.isInteger(expected.expectedTotal) && response.total !== expected.expectedTotal) return false;
    return true;
  }

  function validateVariantAsset(item, options) {
    const expected = isObject(options) ? options : {};
    if (!isObject(item) || !hasText(item.id) || !hasText(item.channel)
      || !hasText(item.title) || !Array.isArray(item.blocks) || !item.blocks.length) return false;
    if (hasText(expected.expectedChannel) && item.channel !== expected.expectedChannel) return false;
    if (hasText(expected.expectedParentAssetId)
      && item.parent_asset_id !== expected.expectedParentAssetId) return false;
    return item.blocks.every((block) => isObject(block) && hasText(block.id)
      && hasText(block.text) && hasText(block.kind) && isInteger(block.order, 0));
  }

  function validateAcademicMatrix(matrix, options) {
    const expected = isObject(options) ? options : {};
    if (!isObject(matrix) || !hasText(matrix.id) || !Array.isArray(matrix.rows)
      || !Array.isArray(matrix.record_ids) || !Array.isArray(matrix.themes)) return false;
    const requestedRecords = new Set(Array.isArray(expected.recordIds) ? expected.recordIds : []);
    const requestedEvidence = new Set(Array.isArray(expected.evidenceIds) ? expected.evidenceIds : []);
    if (!sameMembers(matrix.record_ids, [...requestedRecords])
      || matrix.rows.length !== requestedRecords.size) return false;
    const rowRecordIds = new Set();
    for (const row of matrix.rows) {
      if (!isObject(row) || !hasText(row.record_id) || !requestedRecords.has(row.record_id)
        || rowRecordIds.has(row.record_id) || !hasText(row.citation_label)
        || ![row.methods, row.findings, row.limitations, row.themes, row.evidence_ids].every(Array.isArray)
        || !row.evidence_ids.every((id) => requestedEvidence.has(id))) return false;
      rowRecordIds.add(row.record_id);
    }
    return rowRecordIds.size === requestedRecords.size;
  }

  function validateAcademicOutline(outline, options) {
    const expected = isObject(options) ? options : {};
    if (!isObject(outline) || !hasText(outline.title) || !Array.isArray(outline.sections)
      || !outline.sections.length || !Array.isArray(outline.record_ids)) return false;
    const requestedRecords = new Set(Array.isArray(expected.recordIds) ? expected.recordIds : []);
    if (!outline.record_ids.every((id) => requestedRecords.has(id))) return false;
    return outline.sections.every((section) => isObject(section) && hasText(section.heading)
      && typeof section.purpose === "string" && Array.isArray(section.questions)
      && Array.isArray(section.record_ids) && Array.isArray(section.evidence_ids));
  }

  function validateAcademicAbstract(abstract, options) {
    const expected = isObject(options) ? options : {};
    if (!isObject(abstract) || !hasText(abstract.text) || !Array.isArray(abstract.record_ids)
      || !Array.isArray(abstract.claim_ids) || !Array.isArray(abstract.placeholders)
      || !abstract.placeholders.every((item) => typeof item === "string")) return false;
    const requestedRecords = new Set(Array.isArray(expected.recordIds) ? expected.recordIds : []);
    const requestedClaims = new Set(Array.isArray(expected.claimIds) ? expected.claimIds : []);
    return abstract.record_ids.every((id) => requestedRecords.has(id))
      && abstract.claim_ids.every((id) => requestedClaims.has(id));
  }

  return Object.freeze({
    validateAcademicAbstract,
    validateAcademicMatrix,
    validateAcademicOutline,
    validateCitationAudit,
    validateIntegrityReview,
    validatePage,
    validateProjectReviewEnvelope,
    validateVariantAsset,
  });
});
