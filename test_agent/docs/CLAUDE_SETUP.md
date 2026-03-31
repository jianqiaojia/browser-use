# Claude Sonnet 配置与使用指南

## 背景

GPT-4o 通过 MicrosoftAI LLM Proxy 时，频繁返回 markdown 包裹的 JSON（\`\`\`json...\`\`\`），导致 pydantic 解析失败。Claude Sonnet 对结构化输出的遵循性更好，并使用 native tool use 机制而非 `response_format` 参数，从根本上规避了这个问题。详见 `ARCHITECTURE.md` 和 `WHY_GPT4O_FAILS.md`。

---

## 快速开始

### 前提：确保 LLM Proxy 正在运行

默认地址：`http://localhost:5000`

```bash
# 检查 proxy 进程
tasklist | findstr node
# 或查看端口
netstat -ano | findstr "5000"
```

### 运行测试

```bash
# 基础运行（自动发现所有 *.test.json）
python test_agent/test_runner.py

# 指定模型
python test_agent/test_runner.py --model claude-sonnet-4-5

# 使用代理池（推荐用于反爬虫网站）
python test_agent/test_runner.py --use-proxy-pool

# 自定义代理数量
python test_agent/test_runner.py --use-proxy-pool --max-proxies 50
```

结果保存到：`logs/<test_name>.history.json`

---

## 支持的 Claude 模型

通过 MicrosoftAI LLM Proxy 可用：

| 模型 | 说明 |
|------|------|
| `claude-sonnet-4-5` | 推荐，速度与质量均衡 |
| `claude-sonnet-4-6` | 最新版 Sonnet |
| `claude-opus-4-5` | 更强，更慢 |

---

## 配置说明

### 核心文件

| 文件 | 作用 |
|------|------|
| `test_agent/llm/llm_config.py` | LLM 配置模块，支持 Claude 和 GPT-4o |
| `test_agent/llm/strip_patch.py` | 强制 strip markdown 包裹（aggressive patch） |
| `test_agent/llm/litellm_patch.py` | Usage tokens fallback，防止计数异常 |
| `test_agent/test_runner.py` | 测试运行器 |

### 关键配置

```python
# 默认 proxy 地址
DEFAULT_PROXY_ENDPOINT = 'http://localhost:5000'

# Claude 配置
llm = ChatOpenAI(
    model='claude-sonnet-4-5',
    base_url='http://localhost:5000',
    temperature=0.7,
    add_schema_to_system_prompt=True,
    dont_force_structured_output=True,
)
```

### 环境变量

```bash
# 如果 proxy 不在默认端口
# Windows
set LLM_PROXY_ENDPOINT=http://localhost:8000

# Linux/Mac
export LLM_PROXY_ENDPOINT=http://localhost:8000
```

### 在代码中切换模型

```python
from test_agent.llm.llm_config import get_claude_sonnet, get_gpt4o

llm = get_claude_sonnet()  # 使用 Claude
# llm = get_gpt4o()        # 或继续用 GPT-4o

agent = Agent(task="...", llm=llm, ...)
```

---

## 与 GPT-4o 对比

| 指标 | GPT-4o | Claude | Claude + 代理池 |
|------|--------|--------|----------------|
| JSON 解析成功率 | ⚠️ 70% | ✅ 95% | ✅ 95% |
| 结构化输出 | ⚠️ 需要强制模式 | ✅ 自然遵循 | ✅ 自然遵循 |
| 循环错误恢复 | ❌ 容易卡死 | ✅ 自我修正 | ✅ 自我修正 |
| 反爬虫 | ❌ 容易被封 | ❌ 容易被封 | ✅ IP 轮换 |
| 速度 | ⚡ 快 | ⚡ 中等 | ⚡ 中等 |
| 成本 | 💰 通过 proxy 免费 | 💰 通过 proxy 免费 | 💰 通过 proxy 免费 |

---

## 故障排除

### 连接失败

```bash
# 确认 proxy 在 5000 端口运行
netstat -ano | findstr "5000"
```

### 仍然出现 JSON 解析错误

确认 patches 已加载，启动时应看到：
```
[INFO] Applied aggressive markdown stripping patch
[INFO] Applied litellm usage patch
```

若未出现，检查 `test_agent/llm/strip_patch.py` 和 `litellm_patch.py` 是否被正确导入。

### Model not found

你的 proxy 可能不支持该 Claude 模型，检查 proxy 配置，或回退到 GPT-4o：
```python
llm = get_gpt4o()
```

### Action schema 错误

这是预期的小问题，不影响整体流程。Claude 会在后续步骤中自我修正。

---

## 相关文档

- `ARCHITECTURE.md` — Claude vs GPT-4o 架构深度分析
- `WHY_GPT4O_FAILS.md` — GPT-4o JSON 失败的三层原因
- `ANTI_BOT_AND_PROXY.md` — 反爬虫与代理池方案
