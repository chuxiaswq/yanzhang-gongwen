---
name: gongwen-writing
display_name: 砚章公文写作
display_name_en: Gongwen Writing
description: 使用砚章完成中文公文拟题、写作、改写、审校、文章来源检索、版本保存和 Word 导出；适用于讲话稿、汇报、总结、通知、请示、报告、函等任务。
description_zh: 使用砚章完成中文公文拟题、写作、改写、审校、文章来源检索、版本保存和 Word 导出。
description_en: Draft, revise, review, research, version, and export Chinese official documents with Gongwen.
category: writing
version: 0.1.0-preview.1
author: Yanzhang
allowed-tools: gongwen_get_status, gongwen_get_methods, gongwen_generate_titles, gongwen_generate_document, gongwen_rewrite_text, gongwen_review_document, gongwen_audit_document, gongwen_save_document, gongwen_list_documents, gongwen_read_document, gongwen_list_versions, gongwen_read_version, gongwen_delete_document, gongwen_list_article_sources, gongwen_search_articles, gongwen_read_article, gongwen_get_style_references, gongwen_import_article_text, gongwen_import_article_url, gongwen_collect_articles, gongwen_delete_article, gongwen_export_docx, gongwen_export_documents_zip, gongwen_mail_merge_docx, gongwen_test_model, gongwen_get_model_usage
---

# 砚章公文写作

当用户需要完成公文标题、正文、改写、审校、资料检索、服务端保存或 Word 导出时，优先调用本连接器。始终以用户提供的事实和已选文章来源为内容依据，把权威文章用于学习结构、标题节奏和表达方法，不把参考文章中的具体事实迁移到新文稿。

## 推荐工作流

1. 首次调用先用 `gongwen_get_status` 检查服务和模型模式；再用 `gongwen_get_methods` 获取当前文种适用的标题公式与正文方法论。
2. 用户要求参考党报党刊时，先用 `gongwen_list_article_sources` 查看来源；已有资料用 `gongwen_search_articles` 与 `gongwen_get_style_references`，指定范围采集用 `gongwen_collect_articles`。
3. 先调用 `gongwen_generate_titles`，向用户展示排名、公式和推荐理由。用户选定标题后，再调用 `gongwen_generate_document`。后者会自动保存，记住返回的 `id` 和 `version`，生成后不追加一次 `gongwen_save_document`。
4. `gongwen_generate_document` 的 `preview` 最多 4000 字；用返回的 `id` 调用 `gongwen_read_document` 分块读取全文。针对局部调整使用 `gongwen_rewrite_text`，全文定稿前依次调用 `gongwen_review_document` 和 `gongwen_audit_document`；这三个工具都不保存修改。
5. 只有在保存手工组合或改写后的完整正文时才调用 `gongwen_save_document`。更新既有文稿时先读取最新 `current_version`，再把它作为 `expected_version` 提交。
6. 最终交付根据已保存的 `document_id` 调用 `gongwen_export_docx`、`gongwen_export_documents_zip` 或 `gongwen_mail_merge_docx`；返回导出资源后，保留完整元数据 `artifact_id`、`filename`、`mime`、`size`、`sha256`、`resource_uri`、`created_at`、`expires_at`，ZIP 响应另有 `files`。

## 核心写作工具

| 工具 | 用途 | 关键输入 |
| --- | --- | --- |
| `gongwen_get_status` | 查看服务、存储、模型和能力状态 | 无 |
| `gongwen_get_methods` | 获取文种、标题公式和正文方法论 | `document_type` |
| `gongwen_generate_titles` | 批量拟题、评分、排序 | `topic`、`document_type`、`count`、`formula_ids`、`materials` |
| `gongwen_generate_document` | 按选定标题和方法论生成正文并自动保存版本 | `topic`、`selected_title`、`document_type`、`materials`、`content_methodology_id` |
| `gongwen_rewrite_text` | 润色、压缩、扩写或按指令改写局部文本 | `text`、`instruction`、`mode`、`tone` |
| `gongwen_review_document` | 检查结构、篇幅、长句、模糊表达和占位符 | `title`、`content`、`document_type`、`materials` |
| `gongwen_audit_document` | 将正文主张与用户材料进行事实证据映射 | `title`、`content`、`materials` |

生成标题示例：

```json
{
  "document_type": "讲话稿",
  "topic": "树立和践行正确政绩观",
  "purpose": "区委办公室副主任交流发言",
  "materials": ["用户提供的工作事实和数据"],
  "tone": "凝练有力",
  "count": 10,
  "formula_ids": ["material-parallel", "material-subtitle"]
}
```

生成正文示例：

```json
{
  "document_type": "讲话稿",
  "topic": "树立和践行正确政绩观",
  "selected_title": "在一线察实情、在实干求实效、在长远见真章",
  "purpose": "用于专题研讨交流",
  "audience": "区委理论学习中心组",
  "materials": "在此填入已经核对的本地区事实、数据和时间节点",
  "requirements": "三个排比式小标题；每段首句为观点句；保留待核实项",
  "fact_lock": true,
  "content_methodology_id": "speech-consensus-action"
}
```

生成正文的响应包含 `id`、`version`、`preview`、`preview_truncated` 和标题/提纲元数据。
若让服务生成文稿 ID，省略 `document_id` 与 `expected_version`；若指定全新 ID，两者分别填写
该 ID 与 `0`；若更新已有 ID，`expected_version` 填写刚读取到的 `current_version`。

## 文稿与版本

- `gongwen_generate_document`：生成后已经保存，直接使用返回的 `id` 和 `version`。
- `gongwen_save_document`：保存手工编写、组合或改写后的正文。由服务生成 ID 时同时省略 `document_id` 与 `expected_version`；指定全新 `document_id` 时使用 `expected_version: 0`；更新时使用读取结果里的最新 `current_version`。
- `gongwen_list_documents` / `gongwen_read_document`：按分页或标识读取文稿；正文默认每次读取 8000 字，可用 `next_offset` 继续，单块最多 20000 字。
- `gongwen_list_versions` / `gongwen_read_version`：查询不可变历史版本。
- `gongwen_delete_document`：仅在用户明确提出删除具体文稿时调用，并先复述文稿标题与标识。

发生版本冲突时，读取最新文稿和版本，向用户说明双方差异，再保存合并后的内容。

## 文章来源库

- `gongwen_list_article_sources`：获取当前支持的权威媒体和手动来源。
- `gongwen_search_articles` / `gongwen_read_article`：搜索元数据并按需读取正文。
- `gongwen_get_style_references`：输入搜索后选定的 `article_ids`（1–8 个），提取结构参考；`max_excerpt_chars` 默认 360、范围 80–1000。
- `gongwen_import_article_text`：导入用户粘贴且注明来源的文章。
- `gongwen_import_article_url`：导入用户指定的文章 URL。
- `gongwen_collect_articles`：按 `keywords`、`source_ids`、`start_date`、`end_date` 和 `limit` 执行有界采集。
- `gongwen_delete_article`：仅在用户明确提出删除指定文章来源时调用。

采集示例：

```json
{
  "keywords": ["正确政绩观", "为民造福"],
  "source_ids": ["gmw", "qiushi"],
  "start_date": "2025-01-01",
  "end_date": "2026-09-04",
  "limit": 20
}
```

人民网自动检索默认关闭；仅当部署者显式设置
`GONGWEN_ENABLE_INSECURE_PEOPLE_SEARCH=true`，且用户接受关键词与日期范围经 HTTP 明文传输时，
才把 `people` 加入 `source_ids`。人民网 HTTPS 文章链接仍可用导入工具手工读取。

引用文章来源时附上标题、来源、发布日期和原始 URL。生成正文时只吸收结构和表达特征，事实内容仍以用户材料和审校结果为准。

## 导出与模型

- `gongwen_export_docx`：导出单篇 Word 文档。
- `gongwen_export_documents_zip`：把多篇成稿导出为 ZIP。
- `gongwen_mail_merge_docx`：使用 Word 字段模板和数据行批量生成文档。
- `gongwen_test_model`：检查当前引擎用 `auto`；用户明确要求测试真实模型连接时使用 `engine: server`。
- `gongwen_get_model_usage`：读取服务端记录的模型调用与用量摘要。

模型类工具只使用 `engine` 选择 `auto`、`server` 或 `local`。`auto` 在服务端模型就绪时调用
真实模型，否则使用本地确定性引擎；工具参数中不放 Provider、API Key、模型 URL 或访问令牌。

导出产物默认有效期为 24 小时；使用返回的 `gongwen://exports/{artifact_id}` 读取文件。DOCX
单文件上限 16 MiB，ZIP 单文件上限 64 MiB，过期后重新执行相应导出工具。

MCP 访问令牌由连接器注入。回答中隐藏令牌、模型密钥和完整认证请求头。

## 常见响应处理

- 身份校验提示：引导用户在连接器设置中重新填写 MCP 访问令牌。
- 参数校验提示：按工具返回的字段路径修正参数后再调用。
- 并发版本冲突：读取最新版本并完成差异确认。
- 请求过大：按章节或材料批次拆分，再分别审校和合并。
- 频率限制：遵循服务返回的等待时间后继续。
- 导出资源过期：重新执行相应导出工具取得新资源。

连接器请求超时为 300 秒，用于覆盖长文生成、较长审校与文章采集；状态、方法和列表查询通常
更快完成。
