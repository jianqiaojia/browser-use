# 使用Claude Sonnet替代GPT-4o

## 问题背景

GPT-4o通过MicrosoftAI LLM Proxy时，有时会返回markdown包裹的JSON（```json...```），导致pydantic解析失败。

Claude Sonnet对结构化输出的遵循性更好，基本不会出现这个问题。

## 文件说明

- `test_agent/llm/llm_config.py` - LLM配置模块，支持Claude和GPT-4o
- `test_agent/test_runner.py` - 使用Claude运行测试的脚本

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
python test_agent/test_runner.py --model claude-sonnet-4-5
```

### 3. 运行你的测试用例（使用Claude）

```bash
cd "q:\AI\browser-use"
python test_agent/test_runner.py
```

#### 可选参数：

```bash
# 使用不同的Claude模型
python test_agent/test_runner.py --model claude-sonnet-4-5

# 使用不同的proxy地址
python test_agent/test_runner.py --proxy http://localhost:8000
```

### 4. 对比GPT-4o和Claude的结果

运行同样的测试，对比history文件：
- 结果: `logs/<test_name>.history.json`

## 支持的Claude模型

通过MicrosoftAI LLM Proxy可以使用：

- `claude-sonnet-4-5` - Claude Sonnet 4.5（推荐）
- `claude-sonnet-4-6` - Claude Sonnet 最新版
- `claude-opus-4-5` - Claude Opus（更强，更慢）

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
from test_agent.llm.llm_config import get_claude_sonnet

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
python test_agent/test_runner.py --model claude-sonnet-4-5
```
