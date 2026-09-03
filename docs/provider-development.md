# Provider 扩展

砚章将模型调用、文章发现与文章抓取放在独立 Provider Registry 中。公共写作服务只依赖接口，不直接绑定供应商实现。

## Entry point 组

- `yanzhang.llm_providers`
- `yanzhang.article_discovery_providers`
- `yanzhang.article_fetcher_providers`

第三方包可在自己的 `pyproject.toml` 注册工厂：

```toml
[project.entry-points."yanzhang.llm_providers"]
example = "example_provider:ExampleLLMProvider"
```

工厂需要返回对应接口实例。注册名只使用小写字母、数字、点、下划线或连字符。外部请求、凭据读取和供应商响应解析应全部封装在 Provider 内；测试使用模拟传输，不依赖公网或真实凭据。
