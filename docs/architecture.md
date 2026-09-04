# 砚章·AI文字工作台架构

本文描述 `v0.2.0-preview.2` 的模块边界、数据流、持久化模型和部署约束。设计目标是让公文、
职场沟通、内容传播与学术研究共用一套可追溯写作内核，同时让 Web、HTTP API、MCP 和第三方
扩展保持薄层、可替换和可测试。

## 1. 分层与边界

```text
浏览器 / HTTP 客户端 / MCP 客户端
                 │
        ┌────────┴────────┐
        │                 │
 Web + /api/v2/*      stdio / /mcp
 gongwen_web          gongwen_mcp
        │                 │
        └────────┬────────┘
                 │ 应用服务与组合根
        ┌────────┴────────┐
        │                 │
 yanzhang_core      yanzhang_academic
 通用写作域模型       学术元数据、证据与引用
        │                 │
        └────────┬────────┘
                 │
   SQLite / 本地导出目录 / Provider 与扩展
```

### 入口层

- `gongwen_web` 提供页面、`/api/v2/*` 和兼容 `/api/*`。入口负责认证、限流、请求大小、
  Host/CORS 校验与 JSON 协议转换，不把业务对象退化为页面状态。
- `gongwen_mcp` 在同一注册表上提供本机 stdio 与远程 Streamable HTTP `/mcp`。v0.2 工具采用
  `yanzhang_*` 命名；既有 `gongwen_*` 工具、`gongwen://` Resources 和 Prompts 保留。
- Web 和 MCP 使用同一应用服务与数据目录，因此在网页创建的项目与资产可由 MCP 继续处理。

### 领域层

- `yanzhang_core` 定义项目、任务简报、知识资料、内容块、文字资产、版本、证据、主张、引用、
  场景包、写作配方、六维审校和模型路由。该层不绑定具体模型厂商。
- `yanzhang_academic` 定义文献记录、证据摘录、文献矩阵、研究论断、引用核验、研究完整性检查、
  参考文献格式和审稿回复对象。
- 原公文引擎继续承载 v0.1 接口；兼容层把旧文稿迁移为新文字资产时保留标识、版本与时间信息，
  旧表保持原状。

### 外部边界

- 真实模型请求只从模型 Provider 适配器发出。
- 文章来源与 Crossref、OpenAlex、arXiv 请求只从来源连接器发出。
- 二进制文档解析、导出和发布通过解析器、导出器或发布目标边界完成。
- 核心编排、HTTP/MCP 协议和持久化代码不直接导入第三方厂商 SDK。

## 2. 场景包与配方

场景包是可枚举的能力目录，配方是透明的内容结构，不是隐藏提示词。

| 场景包 | 配方 ID |
| --- | --- |
| 公文与综合材料 `gongwen` | `work-summary`、`briefing-material`、`leadership-speech`、`research-report`、`implementation-plan`、`meeting-minutes` |
| 职场沟通 `workplace` | `work-email`、`weekly-report`、`business-proposal`、`meeting-followup`、`presentation-outline` |
| 内容传播 `media` | `press-release`、`wechat-article`、`social-post`、`short-video-script` |
| 学术与研究写作 `academic` | `literature-review`、`research-outline`、`research-abstract`、`reviewer-response` |

四个场景包共 19 个配方；`leadership-speech` 对应领导讲话，`research-report` 对应调研报告。
每个配方声明所需输入、章节用途、适用渠道、默认标题类型、输出格式和事实策略。任务简报必须与
所选场景包、配方和渠道匹配；无模型配置时，同一配方也能产生确定性本地草稿，便于离线验收。

## 3. 端到端数据流

1. **建项目**：`WritingProject` 隔离任务、资料、词表、资产和审计事件。
2. **填任务简报**：`WritingBrief` 固化目标、受众、渠道、文种、语气、篇幅、约束、关键词、
   配方、关联资料 ID、已采用标题 `selected_title` 和可选的有序结构 `structure_override`。
3. **整理项目资料**：`KnowledgeItem` 保存来源、风格参考、历史稿、术语或笔记；解析器将 TXT、
   Markdown、HTML、DOCX 与可选 PDF 转成受限文本。全文检索仅在当前项目内返回结果。调用方可指定
   稳定 `material_id` 做项目内幂等 upsert；`style_reference` 只进入结构、语气和句式特征上下文，
   不作为正文事实或证据。
4. **做标题与开头实验**：标题引擎按 `title`、`opening`、`section_heading` 或
   `topic_sentence` 生成全部合格公式、全局评分后截取候选；`formula_ids` 可严格筛选公式目录。
   排比、对偶、递进、主副题及三段/四段结构以公式元数据公开，候选记录公式名、修辞标签与
   七维评分理由，便于解释和复现。非标题表达以已采用标题作为当前母稿主题，并按显式关键词、
   自定义结构首节、已采用标题、事实资料标题的顺序解析焦点。关联事实资料只以受限摘录参与
   事实克制评分；确定性引擎不从资料正文抽取新表述，风格资料不进入候选事实边界。
5. **生成母稿**：配方或简报的 `structure_override` 规划有序 `ContentBlock`；组合器读取明确关联
   且经过字符上限裁剪的资料，并优先使用 `selected_title`，生成 `TextAsset` 与首个不可变 `Revision`。
6. **派生渠道变体**：变体通过 `parent_asset_id` 指向母稿，以目标 `channel` 保存；母稿与各变体
   分别维护版本，避免一次修改覆盖所有渠道。
7. **建立证据链**：直接成稿和持久化工作流都先把明确选择的非 `style_reference` 项目资料转为带内容哈希与定位的
   `Evidence`，再把证据 ID 写入内容块，从块提取 `Claim` 并通过 `Citation` 持久化关联。
   学术场景另用 `BibliographicRecord`、`EvidenceSnippet` 与 `ClaimCitationLink` 承载更细的
   来源哈希和页码、段落或字符定位。
8. **六维审校**：审校维度是事实与证据、逻辑与结构、清晰与简洁、受众与语气、语言与规范、
   格式与交付。`checks` 决定本次实际返回和计分的维度；显式实时模式先执行确定性规则，再通过
   `ModelRouter` 选择具备 review 能力的画像完成模型增强。问题关联到具体内容块，修订后形成新的
   `Revision`。
9. **导出或发布**：导出器生成 DOCX、Markdown、文本、HTML、PDF、LaTeX 或引用矩阵 CSV；发布目标接收用户明确选择
   的资产与渠道，不读取未关联的项目数据。

## 4. 核心数据模型

```text
WritingProject
 ├─ WritingBrief ── knowledge_item_ids ──> KnowledgeItem ──> Evidence (kind != style_reference)
 ├─ ProjectTerm
 ├─ TextAsset (master)
 │    ├─ ContentBlock[]
 │    ├─ Revision[]
 │    ├─ Claim[] ── Citation[] ──> Evidence
 │    └─ TextAsset[] (channel variants via parent_asset_id)
 ├─ workflow_runs ──> step_runs
 └─ audit_events

ArtifactMetadata sidecar
 └─ project_id + asset_id + revision_id + creator ──> immutable export bytes
```

### 版本与并发

- 创建文字资产时，资产与首个版本在同一事务写入。
- 后续保存只追加版本快照；`expected_revision` 提供乐观并发检查。
- 内容块按稳定 ID 和唯一递增顺序保存，可锁定单块并保留其资料与证据关系。
- 通用审校使用内容块上的证据 ID 计算数字论断覆盖率；引用矩阵 CSV 输出资料 ID、
  定位、来源 URL、来源哈希和证据摘录，便于回查。
- 工作流步骤、模型画像、父资产和生成元数据记录在版本或工作流关系上，便于复盘来源。
- `brief_id` 在首次保存时绑定项目与完整规范化内容，此后不可变；相同内容重放是幂等读取，内容冲突
  和跨项目复用分别通过稳定、脱敏的 `brief_conflict` 与 `project_scope_error` 边界报告。
- 工作流创建可传入已保存的 `brief_id`；服务校验完整简报与已存内容一致，并在创建响应及工作流投影中
  返回同一 `brief_id`，供客户端绑定母稿、版本与审校结果。
- v0.2 工作流的运行、查询、取消和恢复均按 `project_id` 查找；跨项目标识与缺失标识使用同一
  未找到结果。远端异常只保存稳定错误码与脱敏摘要，不把上游正文、URL 或凭据写入步骤状态。
- v0.2 导出 sidecar 同时记录项目、资产、修订和创建操作；HTTP 与 MCP 资源读取必须携带并校验
  项目 ID。旧未分项目工件只从兼容入口读取。

### SQLite 表

v0.2 写作 schema 当前版本为 3，从旧版库打开时幂等补充项目标签与证据来源哈希。其包含
`projects`、`writing_briefs`、`text_assets`、`revisions`、
`knowledge_items`、`evidence_snippets`、`claims`、`citations`、`workflow_runs`、`step_runs`、
`audit_events` 与 `project_terms`。知识资料建立 SQLite FTS 索引；运行环境优先使用 trigram，
缺少该 tokenizer 时回退为 `unicode61`。

学术 schema 使用独立版本标记，并通过 `project_id` 外键连接同一项目边界。其表包括
`academic_records`、`academic_evidence`、`academic_claims`、`academic_claim_links`、
`academic_matrices`、`academic_matrix_records` 与 `academic_matrix_evidence`；文献记录另建
`academic_records_fts` 全文索引。学术记录、证据、论断、引用链接与矩阵的组合关系均在数据库
层校验，删除项目时按外键关系清理。

## 5. 模型画像与路由

`ModelProfile` 保存非秘密元数据：Provider 名、模型名、能力、上下文、成本/质量/延迟排序、层级
和隐私模式。密钥由运行环境交给 Provider，既不进入模型画像，也不存入文字资产或工具参数。

内置路由预设为：

- `local_only`：只选本地确定性画像；
- `economy`：优先成本与速度；
- `balanced`：平衡质量、速度与成本；
- `quality`：优先质量与长上下文。

路由先按能力、启用状态和隐私策略筛选，再按预设排序；带敏感标记的任务只进入本地画像。远程
模型调用发生在数据库事务之外，结果通过短事务保存，避免长请求占用 SQLite 写锁。审校未显式
请求实时模式时返回 `effective_mode=local` 与实际本地路由；显式请求后才执行模型增强并返回选中
画像，避免 `model_profile_id` 成为无效展示字段。

## 6. 学术数据链

学术记录与正文证据分开处理：

- BibTeX、RIS、CSL-JSON 支持导入与导出；Crossref、OpenAlex、arXiv 用于公开元数据查询。
- 学术 TXT/Markdown、DOCX 与 PDF 适配器统一调用 `yanzhang_core.parse_document`，沿用核心
  文件、解压、活动内容与页数上限；PDF 解析依赖可选组件，并把核心页文本映射为带页码的学术页。
- Crossref、OpenAlex、arXiv 连接器先检查 `Content-Length`，再分块累计响应；单次元数据正文
  始终受 2 MiB 硬上限约束。
- `EvidenceSnippet` 包含文献 `record_id`、来源哈希，以及页码、段落或字符范围。
- `ClaimCitationLink` 只使用调用时提供的文献与匹配来源哈希的证据核验；未知文献 ID、哈希错配
  和低语义/词汇支撑度进入 `needs-review` 或 `invalid` 状态。
- DOI 规范化与参考文献排版不等同于真实性确认；`metadata_verified` 仅由公开连接器来源设置。

更完整的格式、核验规则与人工复核节点见 [academic-writing.md](academic-writing.md)。

## 7. 扩展体系

第三方包通过 Python entry points 注册工厂；组合根负责发现并编目七类工厂。通用扩展点包括：

- `yanzhang.source_connectors`
- `yanzhang.parsers`
- `yanzhang.workflow_steps`
- `yanzhang.template_packs`
- `yanzhang.reviewers`
- `yanzhang.exporters`
- `yanzhang.publish_targets`

当前组合根会自动实例化并注入 `workflow_step`，使其成为可持久化工作流可直接执行的处理器。
其余六类保持可发现 SDK 工厂形式，由显式集成边界构造并接入对应服务；它们出现在能力目录中不会自动
替换内置来源、解析、审校、导出或发布实现。

模型、旧文章来源发现与抓取 Provider 继续使用 `yanzhang.llm_providers`、
`yanzhang.article_discovery_providers` 和 `yanzhang.article_fetcher_providers`。网络 I/O、凭据读取、
响应大小与重试策略留在相应适配器内；扩展测试使用模拟传输。详见
[provider-development.md](provider-development.md)。

## 8. 部署与安全约束

- 本机默认监听 `127.0.0.1`；公网使用 HTTPS、精确 Host/CORS 白名单和可信代理列表。
- Web 与 `/mcp` 使用不同的随机 Bearer Token；MCP 工具参数不承载模型供应商凭据。
- SQLite 个人部署固定一个应用工作进程。Caddy 处理并发连接，应用使用短连接和串行写事务。
- 请求体、文件、文献数量、内容块、重定向、响应体和模型等待时间均有上限。
- 数据目录、浏览器站点数据、导出、备份和第三方供应商记录具有各自生命周期，应分别管理。
- DOCX 导出直接消费 `ContentBlock.kind` 与 `heading_level`，不从纯文本猜测层级；与资产标题相同
  的 title 块只输出一次。项目导出只通过项目嵌套 HTTP 路径或对应 `yanzhang://` Resource 读取。
- 发行包通过白名单与敏感信息扫描排除数据库、文稿、文献全文、媒体、凭据和本机路径。

运行、备份、恢复与排障见 [operations.md](operations.md)，隐私边界见 [../PRIVACY.md](../PRIVACY.md)。

## 9. 兼容策略

| v0.2 首选 | 兼容入口 | 规则 |
| --- | --- | --- |
| `/api/v2/*` | `/api/*` | 两组接口并存；旧公文页面与自动化保持原语义 |
| `yanzhang_*` | `gongwen_*` | 独立工具名并存；不会用 alias 覆盖旧工具 |
| `yanzhang-web` / `yanzhang-mcp` | `gongwen-web` / `gongwen-mcp` | 命令入口指向同一应用 |
| `YANZHANG_*` | `GONGWEN_*` | 同名后缀同时设置时读取 `YANZHANG_*` |
| 新项目/资产表 | 旧文稿与版本表 | 幂等复制到新模型，旧表保持原状 |

新增功能应优先扩展 `/api/v2`、`yanzhang_*` 和领域服务；修订兼容面时同时更新
[http-api-v2.md](http-api-v2.md)、[mcp-codex.md](mcp-codex.md)、
[gongwen-mcp.md](gongwen-mcp.md) 与根目录 README。
