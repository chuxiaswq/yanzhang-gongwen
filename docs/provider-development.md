# 砚章 Provider 与扩展开发

砚章·AI文字工作台把供应商网络、文档处理和交付渠道放在明确的适配器边界内。领域服务只接收
类型化对象或协议，不直接绑定具体模型 SDK、内容平台或学术数据库。

## 两类注册体系

### 既有 Provider Registry

| Entry point 组 | 作用 |
| --- | --- |
| `yanzhang.llm_providers` | 模型生成、改写和审校适配器 |
| `yanzhang.article_discovery_providers` | 文章来源范围发现 |
| `yanzhang.article_fetcher_providers` | 文章页面抓取与正文提取 |

### v0.2 通用写作扩展

| Entry point 组 | `ExtensionKind` | 典型用途 |
| --- | --- | --- |
| `yanzhang.source_connectors` | `source_connector` | 内网知识库、公开元数据或项目资料来源 |
| `yanzhang.parsers` | `parser` | 文本、HTML、DOCX、PDF 等受限解析 |
| `yanzhang.workflow_steps` | `workflow_step` | 检索、标题、提纲、成稿、审校或交付步骤 |
| `yanzhang.template_packs` | `template_pack` | 场景包、配方和组织模板 |
| `yanzhang.reviewers` | `reviewer` | 事实、逻辑、语言、格式或领域审校 |
| `yanzhang.exporters` | `exporter` | DOCX、Markdown、文本、HTML、PDF 等导出 |
| `yanzhang.publish_targets` | `publish_target` | 经用户确认的邮件、内容平台或文档系统发布 |

两套体系并存：旧文章与模型 Provider 保持 API 稳定，新项目能力优先使用通用扩展点。应用组合根
负责创建 Registry 并发现全部七类 entry points，`yanzhang_get_status` 会返回可发现名称目录；
HTTP、MCP 和领域模块不自行扫描插件。

`v0.2` 预览版在启动时自动构造并注册的运行时类型只有 `workflow_step`：工厂返回可调用的
`StepHandler`，扩展名就是 `WorkflowStepDefinition.handler` 中使用的名称。任一工厂构造、
类型校验或步骤注册出错时，启动会终止，避免部分注册的混合状态。

`source_connector`、`parser`、`template_pack`、`reviewer`、`exporter` 和 `publish_target` 在本预览版是
可发现 SDK 工厂：显式集成程序通过 `registry.create(kind, name, **config)` 构造实例，然后接入它所管理的
来源、解析、模板、审校、导出或发布边界。只是出现在状态目录中不会改变内置服务路由。

## 注册示例

第三方包在自己的 `pyproject.toml` 中声明工厂：

```toml
[project.entry-points."yanzhang.source_connectors"]
example-library = "example_yanzhang:build_source_connector"

[project.entry-points."yanzhang.reviewers"]
example-review = "example_yanzhang:build_reviewer"
```

工厂是可调用对象，接收由组合根提供的非秘密配置并返回对应协议实现。名称经过大小写归一化，
并只使用小写字母、数字、点、下划线或连字符；首字符是字母或数字。

运行时注册适合应用内置能力和测试：

```python
from yanzhang_core.plugins import ExtensionKind, ExtensionRegistry

registry = ExtensionRegistry()
registry.register(
    ExtensionKind.SOURCE_CONNECTOR,
    "example-library",
    build_source_connector,
    source="application",
)
connector = registry.create(
    ExtensionKind.SOURCE_CONNECTOR,
    "example-library",
    base_url="https://SOURCE.example/api",
)
```

重复名称默认产生明确错误；只有组合根在清楚替换关系时才使用 `replace=True`。非严格发现会把
第三方载入异常放入 `ExtensionDiscoveryReport.errors`，让其余能力继续启动；发布验收可采用严格
模式，让插件问题直接阻断构建。

## 实现约束

### Provider 中立

- 工作流、场景包、HTTP 与 MCP 只依赖稳定协议和 Pydantic 模型。
- 厂商请求/响应、鉴权方式、重试头和错误码转换都留在适配器内。
- 模型选择通过 `ModelProfile` 与路由策略完成；模型画像只含非秘密元数据。
- 一个 Provider 的增加不应要求在工作流或 MCP 中增加供应商分支。

### 网络与事务

- 网络 I/O 只发生在模型、来源或发布适配器中。
- 对外请求前读取所需对象并结束数据库事务；收到响应后再开启短事务保存结果。
- 为连接、读取、响应体、重定向、重试次数和并发设置边界。
- 来源 URL 采用协议与主机策略；自定义模型基础地址使用部署端精确白名单。
- 错误映射为稳定的超时、限流、未找到、输入错误或上游错误，不把响应正文和凭据写进日志。

### 文件与内容

- 解析器先检查扩展名、媒体类型、魔数、压缩层级、文件数和解压总量，再提取纯文本与定位。
- PDF/DOCX 的宏、脚本、外链和嵌入对象不作为工作流指令执行。
- `KnowledgeItem`、`Evidence`、`ContentBlock` 和学术 `EvidenceSnippet` 都应保留稳定来源关系。
- 导出器只写入分配给当前任务的目录；调用方提供的标题不直接成为文件系统路径。
- 发布目标接收明确资产、目标渠道和操作配置；默认流程不自动发布。

### 凭据

- 工厂构造参数应优先传入凭据句柄或环境解析结果，而不是把密钥塞进领域对象。
- `ModelProfile`、`WritingBrief`、`TextAsset`、工作流记录、审计摘要和 MCP 返回值不保存密钥。
- 异常、日志、测试快照和示例只使用占位凭据。

## 契约测试

每个新扩展至少覆盖：

1. 正常输入到稳定领域对象的映射；
2. 超时、限流、无结果、畸形响应与超大响应；
3. 凭据和上游正文不进入异常文本或日志；
4. 无公网、无真实账号的模拟传输测试；
5. 注册、发现、重复名称和构造失败行为；
6. 网络等待期间没有打开的 SQLite 写事务；
7. 用户数据不会越过项目或资源标识范围。

模型 Provider 还应验证本地确定性回退和结构化输出校验；学术连接器应验证来源标识、
`metadata_verified` 来源规则与 DOI 规范化；解析器应验证损坏文件、压缩炸弹样例和定位信息；
发布目标应验证预览与最终提交是两个独立动作。

## 打包与文档

插件包应固定直接依赖、声明所需 Python 版本，并在 README 记录：

- 注册的 entry point 组和名称；
- 输入/输出模型与大小限制；
- 访问的域名、发送的数据和供应商保留规则；
- 所需凭据和最小权限；
- 超时、重试、速率限制与幂等策略；
- 离线测试命令和版本兼容范围。

扩展不会自动加入官方发行白名单。把插件加入主仓库时，还应更新
[architecture.md](architecture.md)、[configuration.md](configuration.md) 和相应 HTTP/MCP 契约。
