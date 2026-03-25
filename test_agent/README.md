# Browser-Use Test Agent

使用 Claude Sonnet 驱动的浏览器自动化测试框架，基于 browser-use + Edge CDP。

## 📁 目录结构

```
test_agent/
├── test_runner.py              # 主入口：自动发现并运行 test_case/**/*.test.json
├── batch_test_runner.py        # 批量入口：多次重复运行 + 系统级管理（防睡眠、进程清理）
├── config.py                   # 浏览器 / Agent / 代理配置
├── register_custom_actions.py  # 自定义 Action 注册（汇总层）
├── function_registry.py        # 预运行函数注册与执行
├── view.py                     # Pydantic 数据模型
│
├── integration/                # LLM 集成
│   ├── llm_config.py           # Claude LLM 工厂函数
│   ├── llm_anthropic.py        # 原生 Anthropic client 实现
│   ├── strip_patch.py          # Markdown strip patch（防 JSON 解析失败）
│   ├── litellm_patch.py        # LiteLLM usage tokens fallback
│   └── free_proxy_pool.py      # 免费代理池（IP 轮换 + 验证）
│
├── custom_actions/             # 单个 Action 实现
│   ├── cdp_click.py            # CDP 点击（含窗口焦点管理）
│   └── os_click.py             # OS 级鼠标点击（绕过浏览器检测）
│
├── utils/                      # 工具函数
│   ├── uia_helper.py           # Windows UIA 自动填充检测与点击
│   ├── browser_focus_manager.py # 浏览器窗口置顶管理
│   ├── windows_helper.py       # 防睡眠、进程管理
│   ├── tscon_helper.py         # RDP → Console Session 切换
│   ├── screenshot_helper.py    # 截图工具
│   ├── log_file_monitor.py     # Edge 日志文件监控
│   └── log_helper.py           # 日志输出（TeeLogger）
│
├── test_case/                  # 测试定义（*.test.json）
│   └── checkout/
│       └── nike.test.json
│
├── test_script/                # 独立调试脚本（无 LLM 依赖）
│   ├── test_cdp_click.py
│   ├── test_cdp_click_with_tscon.py
│   ├── test_os_click.py
│   └── test_uia_continuous.py
│
├── docs/                       # 技术文档
├── logs/                       # 测试运行日志 & Agent 历史记录
└── _legacy/                    # 旧 Azure OpenAI / GPT-4o 版本（已归档）
```

## 🚀 快速开始

**前提**：激活 venv，启动 LiteLLM proxy（`http://localhost:5000`）

```powershell
cd Q:\AI\browser-use
.venv\Scripts\activate

# 单次运行
python test_agent/test_runner.py

# 指定模型
python test_agent/test_runner.py --model claude-sonnet-4-5

# 批量重复运行（默认 5 次）
python test_agent/batch_test_runner.py --repeat 3
```

## 🔧 可用模型

Proxy 支持的 Claude 模型（`http://localhost:5000/v1/models`）：

| 模型 ID | 说明 |
|---------|------|
| `claude-sonnet-4-5` | 推荐，稳定 |
| `claude-sonnet-4-6` | 最新 Sonnet |
| `claude-opus-4-5` / `claude-opus-4-6` | 更强，更慢 |
| `claude-haiku-4-5` | 最快，适合简单任务 |

## 🔑 关键技术点

### 1. Native Anthropic Client

使用 `ChatAnthropic`（Tool Use 机制）而非 OpenAI-compatible 接口：

```python
from test_agent.integration.llm_config import get_claude_sonnet

llm = get_claude_sonnet(
    model='claude-sonnet-4-5',
    base_url='http://localhost:5000',
)
```

- ✅ Tool Use 强制返回纯 JSON，消除 markdown 包裹问题
- ✅ 解析成功率：GPT-4o ~70% → Claude Native ~98%+

### 2. Markdown Strip Patch（双保险）

`test_runner.py` 启动时自动 import，在 `BaseModel.model_validate_json` 层拦截并清理所有 markdown 包裹：

```python
import test_agent.integration.strip_patch   # 副作用：全局 patch
import test_agent.integration.litellm_patch # 副作用：usage token fallback
```

### 3. 反爬虫最佳实践

⭐ **推荐**：使用干净的 User Data Directory（`config.py` 中配置）

```python
EDGE_STABLE_USER_DATA_DIR = 'Q:\\tmp2'  # 无历史指纹的干净目录
```

详见：`docs/USER_DATA_DIR_SOLUTION.md`

## 📊 效果对比

| 方案 | JSON 解析成功率 | 反爬虫成功率 | 总体 |
|------|:--------------:|:-----------:|:----:|
| GPT-4o | ~70% | — | ~70% |
| Claude (OpenAI-compatible) | ~85% | — | ~85% |
| **Claude Native** | **~98%** | — | **~98%** |
| **Claude Native + Clean Profile** | **~98%** | **~95%** | **~93%** |

## 🔍 故障排查

| 问题 | 解决方案 |
|------|----------|
| `No healthy deployments for model` | 检查 model 名称，用 `curl localhost:5000/v1/models` 确认可用列表 |
| Akamai 429 反爬虫 | 换干净 profile 目录，见 `docs/USER_DATA_DIR_SOLUTION.md` |
| 代理池不生效 | 见 `docs/PROXY_BUG_FIX.md` |
| 自动填充弹窗不出现 | 用 `test_script/test_cdp_click_with_tscon.py` 调试；RDP 场景需先执行 tscon |
| ImportError / venv 问题 | 确认用 `.venv/Scripts/python.exe` 而非系统 Python |

## 📚 文档索引

- `docs/ARCHITECTURE.md` — 整体架构
- `docs/WHY_GPT4O_FAILS.md` — 为什么切换到 Claude
- `docs/USER_DATA_DIR_SOLUTION.md` — 反爬虫最佳实践
- `docs/RDP_Session_Management.md` — RDP 会话管理
- `docs/PROXY_POOL_USAGE.md` — 代理池使用
- `docs/ENHANCED_CLICK.md` — 增强点击方案

---

**维护日期**：2026-03-25
