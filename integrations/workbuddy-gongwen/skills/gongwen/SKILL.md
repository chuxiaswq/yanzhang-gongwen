---
name: yanzhang-writing
display_name: 砚章·AI文字工作台
display_name_en: Yanzhang AI Writing Workbench
description: 使用砚章完成公文、职场沟通、内容传播和学术研究写作；按项目组织资料，先做标题与开头，再生成块编辑母稿和渠道变体，建立证据链，完成六维审校、版本与导出。
description_zh: 使用砚章完成公文、职场沟通、内容传播和学术研究写作，管理项目资料、母稿、变体、证据、审校、版本和交付。
description_en: Create official, workplace, media, and academic writing with project sources, headlines, master drafts, channel variants, evidence, review, revisions, and export.
category: writing
version: 0.2.0-preview.1
author: Yanzhang
allowed-tools: yanzhang_get_status, yanzhang_list_scene_packs, yanzhang_get_scene_pack, yanzhang_create_project, yanzhang_list_projects, yanzhang_get_project, yanzhang_upsert_project_term, yanzhang_list_project_terms, yanzhang_delete_project_term, yanzhang_add_material, yanzhang_list_materials, yanzhang_get_material, yanzhang_search, yanzhang_generate_titles, yanzhang_create_workflow, yanzhang_run_workflow, yanzhang_get_workflow, yanzhang_cancel_workflow, yanzhang_list_assets, yanzhang_get_asset, yanzhang_create_variant, yanzhang_list_revisions, yanzhang_review_asset, yanzhang_export_asset, yanzhang_search_literature, yanzhang_import_literature, yanzhang_list_literature, yanzhang_get_literature, yanzhang_list_evidence, yanzhang_get_evidence, yanzhang_extract_evidence, yanzhang_build_literature_matrix, yanzhang_list_literature_matrices, yanzhang_get_literature_matrix, yanzhang_list_research_claims, yanzhang_get_research_claim, yanzhang_list_citation_links, yanzhang_get_citation_link, yanzhang_verify_citations, yanzhang_format_bibliography, yanzhang_suggest_academic_titles, yanzhang_create_academic_outline, yanzhang_draft_abstract, yanzhang_review_academic_integrity, yanzhang_prepare_rebuttal, gongwen_get_status, gongwen_get_methods, gongwen_generate_titles, gongwen_generate_document, gongwen_rewrite_text, gongwen_review_document, gongwen_audit_document, gongwen_save_document, gongwen_list_documents, gongwen_read_document, gongwen_list_versions, gongwen_read_version, gongwen_delete_document, gongwen_list_article_sources, gongwen_search_articles, gongwen_read_article, gongwen_get_style_references, gongwen_import_article_text, gongwen_import_article_url, gongwen_collect_articles, gongwen_delete_article, gongwen_export_docx, gongwen_export_documents_zip, gongwen_mail_merge_docx, gongwen_test_model, gongwen_get_model_usage
---

# 砚章·AI文字工作台

在用户需要拟题、写作、改写、审校、资料检索、版本管理、渠道改编、学术引用或文件导出时使用
本连接器。默认采用 v0.2 的 `yanzhang_*` 项目工作流；已有公文 ID、旧文章来源或旧自动化任务
继续使用 `gongwen_*` 兼容工具。

## 基本原则

1. 先确认交付目标、受众和渠道，再选择场景包与配方。
2. 项目资料是事实边界。风格参考只用于学习结构、标题节奏和表达方法，不把其中的具体事实迁移
   到新稿。
3. 标题、开头、小标题和段首观点句优先于全文生成；向用户展示候选、评分和推荐理由，再进入
   母稿。
4. 母稿按内容块编辑；渠道内容由 `yanzhang_create_variant` 从明确版本派生，不手工覆盖母稿。
5. 数字、日期、名称、直接引语和关键结论关联 Evidence/Citation；没有来源时保留待核实标记。
6. 交付前运行六维审校：事实与证据、逻辑与结构、清晰与简洁、受众与语气、语言与规范、格式
   与交付。
7. 模型密钥、Web Token 和 MCP Token 不放入工具参数或回答。

## 场景包

| 场景 | 配方 |
| --- | --- |
| `gongwen` 公文与综合材料 | `work-summary`、`briefing-material`、`implementation-plan`、`meeting-minutes` |
| `workplace` 职场沟通 | `work-email`、`weekly-report`、`business-proposal`、`meeting-followup`、`presentation-outline` |
| `media` 内容传播 | `press-release`、`wechat-article`、`social-post`、`short-video-script` |
| `academic` 学术与研究写作 | `literature-review`、`research-outline`、`research-abstract`、`reviewer-response` |

不确定配方时先调用 `yanzhang_list_scene_packs`，再用 `yanzhang_get_scene_pack` 读取章节、渠道、
所需输入和事实策略。

## 通用推荐工作流

1. 调用 `yanzhang_get_status`；确认项目、工作流、模型、学术与导出能力。
2. 查找已有项目；没有匹配项时调用 `yanzhang_create_project`。
3. 把用户确认的事实、风格参考、历史稿和笔记用 `yanzhang_add_material` 保存；首选术语与
   不建议变体用 `yanzhang_upsert_project_term` 维护。长材料用 `yanzhang_get_material` 分块读取，
   统一查询用 `yanzhang_search`。
4. 调用 `yanzhang_generate_titles`。根据任务分别设置 `headline_kind` 为 `title`、`opening`、
   `section_heading` 或 `topic_sentence`，展示排名后让用户确定方向。
5. 调用 `yanzhang_create_workflow`，完整填写 topic、goal、audience、content_type、场景包、配方、
   channel 和 `material_ids`；再用 `yanzhang_run_workflow` 执行。
6. 后台模式用 `yanzhang_get_workflow` 查询。发生中断时先读取最新状态，再从明确的
   `resume_from` 步骤恢复；用户终止任务时用 `yanzhang_cancel_workflow`。
7. 使用返回的资产 ID 调用 `yanzhang_get_asset` 分块读取全文；需要邮件、会议、PPT、网页、社交
   或学术版本时调用 `yanzhang_create_variant`。
8. 用 `yanzhang_review_asset` 审校，结合项目资料逐条处理问题；调用
   `yanzhang_list_revisions` 核对历史版本。
9. 用户确认资产和版本后调用 `yanzhang_export_asset`。DOCX 可选 `template_id=standard`
   或 `brief`；其他格式不携带该字段。保留返回的文件名、媒体类型、大小、哈希、资源标识和版本元数据。

### 标题与开头提示

公文交流发言可先分别生成：

- 8–12 个排比式大标题；
- 3–5 组同构小标题；
- 每节 2–3 个“判断—意义—行动”段首观点句；
- 2 个不同节奏的开场段。

候选比较维度包括主题切合、结构完整、节奏、辨识度、受众适配与事实边界。用户选定大标题和
小标题后，再把选择写入工作流约束，减少正文结构漂移。

## 学术工作流

1. 创建 `academic` 项目并明确研究问题、学科、目标读者、方法说明和目标期刊要求。
2. 先用 `yanzhang_list_literature` 恢复项目已有文献；需继续上次工作时，同步列出 evidence、
   matrices、claims 与 citation-links。已有元数据用 `yanzhang_import_literature` 导入
   BibTeX、RIS 或 CSL-JSON；需要公开查找时用 `yanzhang_search_literature`。两种方式返回的记录
   都保存在当前项目。
3. 用 `yanzhang_get_literature` 核对题名、作者、年份、DOI、来源和
   `metadata_verified`。DOI 规范化本身不是元数据核验。
4. 从用户提供的原文提取 `yanzhang_extract_evidence`；保留 `record_id`、来源哈希、页码、段落
   或字符位置。
5. `yanzhang_build_literature_matrix` 比较研究对象、方法、发现、局限和主题；随后调用
   `yanzhang_suggest_academic_titles` 与 `yanzhang_create_academic_outline`。
6. 对正文中的关键 `ResearchClaim` 建立 `ClaimCitationLink`，用
   `yanzhang_verify_citations` 检查未知文献、来源错配和支撑度。
7. `yanzhang_draft_abstract` 只使用已确认的研究简报、主张和引用链；缺少结果或方法信息时保留
   明确待补项。
8. `yanzhang_review_academic_integrity` 检查缺引、元数据缺失、直接引语缺页码、数字证据、来源
   哈希和期刊要求。方法、统计和核心结论交给作者逐项复核。
9. `yanzhang_format_bibliography` 提供 GB/T 7714、APA、MLA、Chicago 基础著录；对照目标期刊
   的具体版本和格式细则。审稿回复用 `yanzhang_prepare_rebuttal`，每条回复关联实际修改位置。

列表工具均使用 `limit` / `offset` 分页，单条读取工具在继续写作前复核完整记录。

## 兼容公文流程

当用户给出旧 `document_id`、旧文章 ID 或明确沿用既有公文自动化时：

1. `gongwen_get_status` 与 `gongwen_get_methods` 检查服务和方法；
2. `gongwen_search_articles` / `gongwen_get_style_references` 选择结构参考，范围采集使用
   `gongwen_collect_articles`；
3. `gongwen_generate_titles` 先拟题，再用 `gongwen_generate_document` 自动保存；生成后不要紧接
   着调用 `gongwen_save_document`；
4. 返回的 `preview` 最多 4000 字，全文由 `gongwen_read_document` 分块读取；
5. 局部处理用 `gongwen_rewrite_text`，定稿前调用 `gongwen_review_document` 和
   `gongwen_audit_document`；这些工具不保存修改；
6. 只有保存手工组合后的完整正文才用 `gongwen_save_document`。更新时传最新
   `current_version` 作为 `expected_version`；
7. 最终根据保存的 ID 调用 DOCX、ZIP 或 Word 字段批量导出工具。

人民网自动检索受部署开关控制；未启用时使用 HTTPS 文章链接手工导入或选择其他 HTTPS 来源。
引用文章来源时附标题、来源、发布日期和原始 URL。

## 响应与故障处理

- 参数提示：按字段路径修正枚举、长度、列表或未定义字段。
- 项目资源未找到：核对 `project_id` 与资源 ID 是否属于同一项目。
- 后台任务超时：先查询工作流，确认步骤和输出资产，再决定恢复。
- 并发版本冲突：读取最新版本，比较内容块后以新版本号保存合并结果。
- 请求过大：按章节、资料或文献批次分块处理，并保留原来源定位。
- 频率限制：遵循等待时间并缩小并发或检索数量。
- 导出过期：从原资产和指定版本重新执行导出。
- 引用提示：未知文献、哈希错配、缺页码、数字无证据和低支撑度保留为人工复核项。

连接器超时为 300 秒，用于长文生成、审校、外部检索和导出；状态、目录和列表操作通常更快。
