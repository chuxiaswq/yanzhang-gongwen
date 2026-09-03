# 预览版发布流程

## 1. 准备

1. 更新 `pyproject.toml` 的 PEP 440 版本和 `CHANGELOG.md`。
2. 运行全部测试、静态检查和 `scripts/release_audit.py`。
3. 使用 `uv lock` 更新锁文件，并以 `uv export` 刷新 Docker 依赖锁。
4. 构建 wheel 与 sdist，再对构建产物逐成员检查。
5. 生成并核对 `dist/SHA256SUMS`。

```bash
export UV_PROJECT_ENVIRONMENT="${TMPDIR:-/tmp}/yanzhang-venv"
uv sync --frozen --all-extras
PYTHONDONTWRITEBYTECODE=1 GONGWEN_DATA_DIR="$(mktemp -d)" uv run pytest -p no:cacheprovider
uv run ruff check --no-cache .
uv run ruff format --check --no-cache .
uv run mypy --cache-dir="${TMPDIR:-/tmp}/yanzhang-mypy-cache" gongwen_web gongwen_mcp yanzhang
python scripts/release_audit.py
uv build
python scripts/package_connector.py dist
python scripts/release_audit.py --artifacts dist
python scripts/write_checksums.py dist
(cd dist && sha256sum -c SHA256SUMS)
```

macOS 可使用 `shasum -a 256` 手动复核。

## 2. 提交与标签

提交中只保留白名单内的源码和示例。预览标签与包版本映射示例：

```text
Python: 0.1.0b1
Git tag: v0.1.0-preview.1
```

推送标签前在 GitHub 仓库设置中启用 Private vulnerability reporting，并检查 Actions 的默认权限。发布工作流只申请 `contents: write`，用于创建 GitHub 预发布与上传已审计产物。

## 3. 发布后复核

- 下载 wheel、sdist、`yanzhang-workbuddy-connector-0.1.0-preview.1.zip` 和
  `SHA256SUMS`，从下载位置重新核对哈希。
- 在空虚拟环境安装 wheel，运行 `gongwen-web` 健康检查和 MCP initialize/tools/list。
- 检查发行页文件列表中没有 `.env`、数据库、备份、文章、文稿或日志。
- 记录测试摘要与已知预览限制。
