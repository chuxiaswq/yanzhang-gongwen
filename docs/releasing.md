# 砚章预览版发布流程

本清单适用于“砚章·AI文字工作台”`v0.2.0-preview.2`。Python 包遵循 PEP 440，发布标签和
WorkBuddy Connector 使用面向用户的 preview 版本。

## 1. 版本映射

```text
Python package: 0.2.0b2
Git tag:        v0.2.0-preview.2
Connector:      0.2.0-preview.2
```

同一发布中的 `pyproject.toml`、`CHANGELOG.md`、Connector 元数据与 Skill frontmatter 必须一致。
标签仍以 `vX.Y.Z-preview.N` 表示，Python 包对应 `X.Y.ZbN`。

## 2. 源码准备

1. 更新版本、更新记录和用户可见能力说明。
2. 检查 `/api/v2/*`、`yanzhang_*`、场景包、学术格式与环境变量文档和实际契约一致。
3. 保留 `/api/*`、`gongwen_*`、`gongwen://`、旧 Prompts 与 `GONGWEN_*` 兼容测试。
4. 更新 `uv.lock`，再从锁定解析结果生成运行时和构建依赖锁。
5. 使用模拟传输运行全部测试；测试环境不读取真实凭据或访问公网。
6. 运行源码白名单与敏感信息审计。

```bash
export UV_PROJECT_ENVIRONMENT="${TMPDIR:-/tmp}/yanzhang-venv"
uv sync --frozen --all-extras
PYTHONDONTWRITEBYTECODE=1 YANZHANG_DATA_DIR="$(mktemp -d)" \
  uv run pytest -p no:cacheprovider
uv run ruff check --no-cache .
uv run ruff format --check --no-cache .
uv run mypy --cache-dir="${TMPDIR:-/tmp}/yanzhang-mypy-cache" \
  gongwen_web gongwen_mcp yanzhang yanzhang_core yanzhang_academic
uv lock --check
uv export --frozen --all-extras --no-emit-project --format requirements-txt \
  --output-file "${TMPDIR:-/tmp}/yanzhang-all-requirements.txt"
uv run pip-audit --requirement "${TMPDIR:-/tmp}/yanzhang-all-requirements.txt" \
  --progress-spinner off
python scripts/release_audit.py
```

Docker 依赖锁从 `uv.lock` 生成：

```bash
uv export --format requirements.txt --no-dev --no-emit-project --locked \
  --output-file deploy/gongwen/requirements.lock
uv pip compile deploy/gongwen/requirements-build.in \
  --constraints deploy/gongwen/requirements.lock --generate-hashes --universal \
  --python-version 3.12 --no-annotate \
  --output-file deploy/gongwen/requirements-build.lock
```

随后运行部署静态检查、Compose 解析与无凭据冒烟测试。

## 3. 构建与逐成员审计

```bash
uv build
python scripts/package_connector.py dist
python scripts/release_audit.py --artifacts dist
python scripts/write_checksums.py dist
(cd dist && sha256sum -c SHA256SUMS)
```

macOS 可使用 `shasum -a 256` 手动复核。预期产物包括：

- `yanzhang_gongwen-0.2.0b2-py3-none-any.whl`
- `yanzhang_gongwen-0.2.0b2.tar.gz`
- `yanzhang-workbuddy-connector-0.2.0-preview.2.zip`
- `SHA256SUMS`

发布审计会检查每个归档成员、文件类型、路径、大小、凭据特征和本机绝对路径。发行内容不含
`.env`、数据库、备份、项目资料、文章、文献全文、文稿、日志、导出或媒体文件。

## 4. 安装产物验收

在空目录和空虚拟环境中执行：

1. 安装 wheel，验证 `yanzhang-web --help`、`yanzhang-mcp --help`；
2. 同时验证兼容命令 `gongwen-web --help`、`gongwen-mcp --help`；
3. 以临时 `YANZHANG_DATA_DIR` 启动 Web，检查健康、就绪与 `/api/v2` 能力发现；
4. 运行 stdio MCP `initialize` 与 `tools/list`，核对 45 个 `yanzhang_*` 和既有 26 个
   `gongwen_*`；
5. 用确定性模式完成项目→资料→标题→母稿→变体→六维审校→导出流程；
6. 用最小 BibTeX、RIS 和 CSL-JSON 样例完成导入/导出、证据定位与引用核验；
7. 构建 Connector ZIP 两次并比较字节，确认结果可重复。

真实模型、文章来源和学术元数据服务不参与自动发布测试。人工联网验收使用专门测试账户、最小
虚构材料和已审核 HTTPS 端点，并在完成后轮换临时凭据。

## 5. 提交、标签与 GitHub

推送标签前：

- 工作树只包含白名单内的源码、文档、配置样例和锁文件；
- GitHub 仓库启用 Private vulnerability reporting；
- Actions 使用固定 40 位提交 SHA，默认权限最小化；
- 发布工作流只申请创建 GitHub 预发布和上传产物所需的 `contents: write`；
- CI 与本地命令均使用失效代理或模拟传输验证离线测试边界。

推送 `v0.2.0-preview.2` 后，确认 GitHub 条目标记为预发布，说明中列出四场景、兼容面、迁移和
已知预览边界。

## 6. 发布后复核

- 从发行页重新下载所有产物并校验 `SHA256SUMS`；
- 在另一台空环境重复 wheel 与 Connector 安装验收；
- 核对发行页没有未列入清单的附件；
- 执行一次 v0.1 数据快照升级和回退演练；
- 在 HTTPS 测试域名验证 Web Token、MCP Token、Host/CORS、请求大小和速率限制；
- 抽查学术结果中的 `metadata_verified`、来源哈希、定位和人工复核提示；
- 记录测试摘要、已知限制、升级步骤和回退点，不记录凭据或用户内容。

问题修复进入 [../CHANGELOG.md](../CHANGELOG.md)；安全报告遵循
[../SECURITY.md](../SECURITY.md)，生产变更与恢复遵循 [operations.md](operations.md)。
