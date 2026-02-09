# 使用Claude Sonnet替代GPT-4o

## 问题背景

GPT-4o通过MicrosoftAI LLM Proxy时，有时会返回markdown包裹的JSON（```json...```），导致pydantic解析失败。

Claude Sonnet对结构化输出的遵循性更好，基本不会出现这个问题。

## 文件说明

- `test_agent/llm_config.py` - LLM配置模块，支持Claude和GPT-4o
- `test_runner_claude.py` - 使用Claude运行测试的脚本
- `test_claude_quick.py` - 快速测试Claude是否配置正确

## 使用方法

### 1. 确保你的MicrosoftAI LLM Proxy正在运行

检查proxy日志，应该看到类似：
```
[INFO] Copilot token obtained, expires at: ...
[INFO] Tokens saved to C:\Users\...\litellm\github_copilot
```

默认proxy地址：`http://localhost:5000`

### 2. 快速测试Claude配置

```bash
cd "q:\AI\browser-use"
uv run python test_claude_quick.py
```

应该看到：
```
✅ Success!
Response: {"message": "Hello from Claude!"}
```

### 3. 运行你的测试用例（使用Claude）

```bash
cd "q:\AI\browser-use"
uv run python test_runner_claude.py "test_agent/test_case/your_test.json"
```

#### 可选参数：

```bash
# 使用不同的Claude模型
uv run python test_runner_claude.py test.json --model claude-3-5-sonnet-20241022

# 使用不同的proxy地址
uv run python test_runner_claude.py test.json --proxy http://localhost:8000
```

### 4. 对比GPT-4o和Claude的结果

运行同样的测试，对比history文件：
- GPT-4o: `test_case/your_test.history.json`
- Claude: `test_case/your_test_claude.history.json`

## 支持的Claude模型

通过MicrosoftAI LLM Proxy可以使用：

- `claude-sonnet-4-20250514` - Claude Sonnet 4（最新，推荐）
- `claude-3-5-sonnet-20241022` - Claude 3.5 Sonnet v2
- `claude-3-5-sonnet-20240620` - Claude 3.5 Sonnet v1

## 配置说明

如果你的proxy地址不是默认的 `http://localhost:5000`，可以设置环境变量：

```bash
# Windows
set LLM_PROXY_ENDPOINT=http://localhost:8000

# Linux/Mac
export LLM_PROXY_ENDPOINT=http://localhost:8000
```

## 在代码中切换模型

如果你想在自己的代码中使用：

```python
from test_agent.llm_config import get_claude_sonnet, get_gpt4o

# 使用Claude
llm = get_claude_sonnet()

# 或继续使用GPT-4o
llm = get_gpt4o()

# 然后像往常一样创建Agent
agent = Agent(
    task="...",
    llm=llm,
    ...
)
```

## 预期改进

使用Claude后，应该看到：

1. ✅ 不再出现 "Invalid JSON: expected value" 错误
2. ✅ 更稳定的结构化输出
3. ✅ 更好的指令遵循能力
4. ⚡ 可能略慢一点，但更可靠

## 故障排除

### 错误：Connection refused

确保MicrosoftAI LLM Proxy正在运行：
```bash
# 检查proxy进程
tasklist | findstr node
```

### 错误：Model not found

你的proxy可能不支持该Claude模型。检查proxy配置或使用GPT-4o：
```python
llm = get_gpt4o()
```

### 错误：仍然出现JSON解析错误

尝试使用更新的Claude模型：
```bash
uv run python test_runner_claude.py test.json --model claude-sonnet-4-20250514
```
