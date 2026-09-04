# 学术与研究写作

`v0.2.0-preview.1` 的学术包以真实文献记录和可定位证据为输入，服务于文献综述、研究提纲、
研究摘要和审稿意见回复。它将“元数据记录”“原文摘录”“作者论断”“引用关系”分开建模，
便于检查来源链路；最终学术判断仍由作者完成。

## 1. 支持的任务

| 配方 | 标识 | 结构重点 |
| --- | --- | --- |
| 文献综述 | `literature-review` | 研究范围、主题脉络、证据与分歧、研究空白 |
| 研究提纲 | `research-outline` | 研究问题、分析框架、资料与方法、章节结构 |
| 研究摘要 | `research-abstract` | 背景与目的、方法、结果、结论与边界 |
| 审稿意见回复 | `reviewer-response` | 意见复述、回应、修改内容、稿件位置和状态 |

学术场景与其他场景共用项目、任务简报、知识资料、文字资产、内容块、版本和导出能力。研究专用
对象包括：

- `ResearchBrief`：学科、研究问题、目标读者、文种、关键词、方法说明和约束；
- `BibliographicRecord`：结构化文献著录及导入来源；
- `EvidenceSnippet`：与文献 ID、来源哈希和位置绑定的原文摘录；
- `ResearchClaim`：正文中的可核查论断；
- `ClaimCitationLink`：论断、文献和证据摘录之间的可审计关系；
- `LiteratureMatrix`：按研究对象、方法、发现、局限和主题比较文献；
- `JournalProfile`：目标刊物的必备栏目、题名/摘要/全文篇幅、引用样式和人工核对规则；
- `ReviewComment` / `RebuttalItem`：完整性问题与逐条审稿回复。

## 2. 推荐工作流

### 第一步：建立研究简报

先明确研究问题、学科、文种、受众、资料范围、目标语言、目标期刊和方法边界。研究简报应写明
哪些结论已有数据、哪些只有假设、哪些需要新增证据。

### 第二步：导入或查询文献

本地双向格式：

- BibTeX：导入与导出；
- RIS：导入与导出；
- CSL-JSON：导入与导出。

公开元数据连接器：

- Crossref：按查询条件或 DOI 获取出版元数据；
- OpenAlex：按主题、题名或作者检索开放学术元数据；
- arXiv：按 arXiv 标识或检索条件获取预印本记录。

连接器只在用户发起查询时访问外部服务，并实施超时、速率控制和最多 3 次的有界重试。仅连接/
超时异常、HTTP 429 与 5xx 状态进入短退避重试；其他 4xx 立即返回明确错误。检索词最多
1000 字符。查询结果
会直接保存到当前项目；先检查题名、作者、年份、载体、卷期页、DOI 与 URL，再决定是否用于正文。
连接器先用 `Content-Length` 拒绝已声明的超限响应，再以 64 KiB 分块读取并累计解码后的正文；
无论服务是否发送长度头，单次元数据响应的硬上限均为 2 MiB。

### 第三步：提取可定位证据

可从用户提供的文本、可选 PDF 解析器或 DOCX 标准包中提取证据摘录。每条摘录保留：

- `record_id` 与 `record_source_hash`；
- 摘录正文及 `content_hash`；
- 证据类型，如背景、方法、发现、局限或定义；
- 可用的章节、页码、段落序号、字符起止位置；
- 提取方式：手工、确定性规则或解析器。

PDF 页码以解析结果为准；扫描件、复杂双栏、脚注、公式和表格可能需要回到原文件校正。DOCX
处理聚焦标准 OOXML 文本，不执行宏、脚本或嵌入对象。

学术包保留 `PlainTextExtractor`、`DOCXTextExtractor`、`PDFTextExtractor` 与学术
`ParsedDocument` 接口，内部统一委托 `yanzhang_core.parse_document`。因此它与项目资料导入
共用 12 MiB 输入、200 万字符、512 个 DOCX 成员、单成员 8 MiB、解压合计 32 MiB、500 页
PDF 等硬上限，并共享路径、宏、活动内容、外部关系与 PDF 动作检查；构造器传入更小限制时采用
更小值。PDF 页文本再映射回学术接口的 `pages` 字段。

### 第四步：建立文献矩阵

选择真实存在的 `record_ids` 和 `evidence_ids` 构造文献矩阵。矩阵是比较视图，不把模型概括
当作新来源；方法、发现和局限应能回到对应记录或证据摘录。

### 第五步：核验论断与引用

为每项需要引用的 `ResearchClaim` 建立 `ClaimCitationLink`。核验器只在调用时传入的
`BibliographicRecord` 和 `EvidenceSnippet` 集合中判断：

1. 文献 ID 是否存在；
2. 证据是否属于该文献且来源哈希匹配；
3. 摘录与论断是否具有足够词汇或语义支撑；
4. 关系是支持、反驳还是背景；
5. 直接引语是否具有页码或等价定位。

链接状态分为 `verified`、`needs-review` 和 `invalid`。覆盖率只表示需要引用的论断中有多少
建立了合格链接，不表示研究结论本身已经证明。

### 第六步：成文、完整性审校与交付

标题建议、研究提纲和摘要只使用所选记录、证据和作者确认的论断。完整性审校重点发现：缺失
引用、著录字段缺失、直接引语缺定位、数字论断缺证据、来源哈希错配、方法/统计结论待复核、
期刊结构或篇幅偏差。处理完审校项后再格式化参考文献、保存版本并导出。

完整性审校会读取本次提交的 `manuscript`，检查传入论断是否能在稿件正文中定位；传入
`JournalProfile` 时，还会逐项检查：

- `required_sections`：识别 Markdown 标题、中文章节编号、阿拉伯数字编号和“摘要：正文”形式；
- `title_max_characters`：以首个非空行为题名，去除 Markdown 标记与空白后计字符；
- `abstract_max_characters`：提取“摘要/Abstract”至下一个标题或关键词之前的正文，去除空白后计字符；
- `manuscript_max_words`：每个中日韩统一表意字符计一词，拉丁字母或数字连续组计一词；
- `custom_rules`：每条规则均生成独立的“需人工逐项核对”审校项，系统不推定已经满足。

缺少必备章节或超过明确上限会使 `passed=false`。找不到摘要正文时会给出待核对提示；图表、
脚注、公式和参考文献是否计入篇幅，仍以目标刊物的最新投稿指南为准。调用不传 `manuscript`
与 `journal` 的底层 Python 接口时，保持原有的引用、元数据和证据谱系审校行为。

## 3. Web、HTTP 与 MCP

Web 的“学术研究”视图组织研究简报、文献、证据、文献矩阵、论断链接、提纲/摘要、完整性审校
和审稿回复。HTTP 先创建 `scenario_pack_id=academic` 的项目；项目资料、母稿和版本使用
`/api/v2/projects/{project_id}/...` 通用路线，文献与研究写作使用同一项目下的 21 个
`/api/v2/projects/{project_id}/academic/...` 路线。完整路径和请求字段见
[http-api-v2.md](http-api-v2.md)。对应 MCP 工具为：

- `yanzhang_search_literature`
- `yanzhang_import_literature`
- `yanzhang_list_literature`
- `yanzhang_get_literature`
- `yanzhang_list_evidence`
- `yanzhang_get_evidence`
- `yanzhang_extract_evidence`
- `yanzhang_build_literature_matrix`
- `yanzhang_list_literature_matrices`
- `yanzhang_get_literature_matrix`
- `yanzhang_list_research_claims`
- `yanzhang_get_research_claim`
- `yanzhang_list_citation_links`
- `yanzhang_get_citation_link`
- `yanzhang_verify_citations`
- `yanzhang_format_bibliography`
- `yanzhang_suggest_academic_titles`
- `yanzhang_create_academic_outline`
- `yanzhang_draft_abstract`
- `yanzhang_review_academic_integrity`
- `yanzhang_prepare_rebuttal`

MCP `tools/list` 返回实际输入 Schema。MCP 输入模型采用封闭 JSON Schema；文献记录、证据和
论断均使用项目内标识关联。专用工具的字段、默认值与数量上限见
[gongwen-mcp.md](gongwen-mcp.md)。

五类持久化研究对象都有项目级 list/get 接口。列表统一返回
`items/count/total/limit/offset/has_more`；文献列表可用 `query` 检索，证据可按
`record_id` 筛选，引用链可按 `claim_id` / `record_id` / `evidence_id` 筛选。Web 在项目
切换与页面刷新时从服务端分页恢复这些对象，不把浏览器本地缓存作为可发现性的唯一来源。

MCP 亦提供 `yanzhang://projects/{project_id}/academic/...` Resources：文献、证据、矩阵、
主张与引用链均各有集合 URI 和按 ID 读取 URI；集合 Resource 返回前 100 条并用
`has_more` 指示是否应改用分页列表工具继续读取。

## 4. 引用格式

内置格式器提供以下基础著录输出：

- GB/T 7714 `gb-t-7714`
- APA `apa`
- MLA `mla`
- Chicago `chicago`

这些输出覆盖常见字段和基础顺序。不同学校、出版社、期刊与样式版本可能调整作者缩写、标点、
网络资源日期、大小写、页码、DOI 呈现和文内引用方式，投稿前应按目标指南逐项核对。

## 5. 真实性和研究诚信边界

- DOI 规范化只清理常见 URL/前缀、大小写和尾部标点，不据此验证 DOI 是否解析到目标文献。
- `metadata_verified=true` 只说明记录来自本次公开元数据连接器响应；它不评价论文真实性、
  同行评议状态、撤稿状态、数据质量或结论可靠性。
- 手工、BibTeX、RIS 和 CSL-JSON 导入保留原始来源哈希，默认仍需人工核对元数据。
- 来源哈希证明摘录关联到哪一版输入；哈希匹配不评价摘录是否完整、翻译是否准确或解释是否恰当。
- 语义/词汇支持度用于分流复核，不替代全文阅读。低支撑、冲突、未知 ID 和错配来源会被标记，
  不会被提升为已核验引用。
- 摘要、提纲、综述和审稿回复中的方法、统计数值、因果关系、创新性、局限和最终结论由作者
  逐条核对。引用覆盖率也不代表查重、版权、伦理审批或投稿合规已经完成。

## 6. 数据与网络

本地导入的文献记录、证据摘录、研究主张、引用链和文献矩阵保存在项目数据目录。元数据查询会把检索条件发送到
所选公开服务；真实模型步骤会把本次选中的研究简报、记录摘要、证据或正文发往配置的模型
Provider。详细数据边界见 [PRIVACY.md](../PRIVACY.md)，服务端配置见
[configuration.md](configuration.md)。
