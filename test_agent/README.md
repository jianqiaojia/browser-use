# Browser-Use Test Agent

使用 Claude Sonnet 驱动的浏览器自动化测试框架，基于 browser-use + Edge CDP。

## 📁 目录结构

```
test_agent/
├── test_runner.py              # 主入口：自动发现并运行 test_case/**/*.test.json
├── test_runner_batch.py        # 批量入口：多次重复运行 + 系统级管理（防睡眠、进程清理）
├── config.py                   # 浏览器 / Agent / 代理配置
├── models.py                   # Pydantic 数据模型（TestCase, ECTest, TestStep 等）
├── register_custom_actions.py  # 自定义 Action 注册（汇总层）
├── requirements.txt            # pip 依赖
│
├── llm/                        # LLM 集成
│   ├── llm_config.py           # Claude LLM 工厂函数
│   ├── llm_anthropic.py        # 原生 Anthropic client 实现
│   ├── strip_patch.py          # Markdown strip patch（防 JSON 解析失败）
│   ├── litellm_patch.py        # LiteLLM usage tokens fallback
│   └── free_proxy_pool.py      # 免费代理池（IP 轮换 + 验证）
│
├── actions/                    # 单个 Action 实现
│   ├── cdp_click.py            # CDP 点击（含窗口焦点管理）
│   └── os_click.py             # OS 级鼠标点击（绕过浏览器检测）
│
├── scripts/                    # 工具函数
│   ├── uia_helper.py           # Windows UIA 自动填充检测与点击
│   ├── email_helper.py         # Microsoft Graph API 邮件读取（获取验证码）
│   ├── browser_focus_manager.py # 浏览器窗口置顶管理
│   ├── windows_helper.py       # 防睡眠、进程管理
│   ├── tscon_helper.py         # RDP → Console Session 切换
│   ├── tscon_worker.ps1        # tscon PowerShell 辅助脚本
│   ├── screenshot_helper.py    # 截图工具
│   ├── log_file_monitor.py     # Edge 日志文件监控
│   └── log_helper.py           # 日志输出（TeeLogger）
│   └── debug/                  # 独立调试脚本（无 LLM 依赖）
│       ├── test_cdp_click.py
│       ├── test_cdp_click_with_tscon.py
│       ├── test_os_click.py
│       └── test_uia_continuous.py
│
├── test_case/                  # 测试定义（*.test.json）
│   └── nike.test.json
│
├── docs/                       # 技术文档
├── logs/                       # 测试运行日志 & Agent 历史记录
└── _legacy/                    # 旧 Azure OpenAI / GPT-4o 版本（已归档）
```

## 🔧 环境安装

在 `test_agent/` 目录下建独立 venv：

```powershell
cd C:\repos\browser-use\test_agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` 里的 `-e ..` 会把上层 `browser-use` 以 editable 模式装进 venv，同时装好 `comtypes`、`azure-identity`、`msal`、`pyautogui` 等 test_agent 特有依赖。

## ⚠️ 新环境初始化（必读）

在新机器或新 profile 上首次运行前，需要手动完成以下步骤，否则 autofill 不会触发。

### 1. 在 Edge 中添加信用卡

打开 Edge → 设置 → 个人信息 → 付款方式，手动添加一张信用卡：

- 卡号：4514 6176 6302 3788
- 持卡人：rong sun
- CVV：407

### 2. 等待全局配置同步（约 5 分钟）

添加完信用卡后，Edge 需要从服务器拉取 autofill 全局配置（express checkout 等功能开关）。
**等待约 5 分钟**再运行测试，否则 autofill popup 不会出现。

### 3. 确认 Edge 日志路径

Edge 的 `chrome_debug.log` 实际位置因机器而异，需在 `config.py` 中正确配置 `EDGE_STABLE_LOG_FILE_PATH`。

常见路径：
- `C:\Users\<用户名>\AppData\Local\Microsoft\Edge\User Data\chrome_debug.log`（User Data 根目录，**大多数情况**）
- `C:\Users\<用户名>\AppData\Local\Microsoft\Edge\User Data\Profile 2\chrome_debug.log`（Profile 子目录，较少见）

确认方法：Edge 启动时加 `--enable-logging --v=1` 参数，然后在 User Data 目录下查找 `chrome_debug.log`。

### 4. 确认 Outlook 桌面版已登录

测试中若 Nike 触发邮件验证码流程，agent 会调用 `get_email_verification_code` action，通过 **Outlook 桌面版 COM/MAPI** 接口直接读取 `happyautoec@outlook.com` 收件箱。

**前提**：机器上安装了经典版 Outlook（非 New Outlook），且 `happyautoec@outlook.com` 已在 Outlook 中登录。无需任何 OAuth 授权或 token 配置。

验证方式：

```powershell
cd C:\repos\browser-use\test_agent
.venv\Scripts\python.exe scripts\email_helper.py
```

输出 `Found code: XXXXXXXX` 即表示 Outlook COM 连接正常。

### 5. 禁用 Microsoft Shopping(可以不做)

Edge 扩展和内置 Shopping 弹窗会抢占 OS 焦点，导致 autofill popup 被关闭。
**禁用 Microsoft Shopping（内置功能，无法通过扩展页关闭）：** 以管理员身份运行：

```powershell
reg add "HKLM\SOFTWARE\Policies\Microsoft\Edge" /v EdgeShoppingAssistantEnabled /t REG_DWORD /d 0 /f
```

重启 Edge 生效。

---

**前提**：激活 venv，启动 LiteLLM proxy（`http://localhost:5000`）

```powershell
cd C:\repos\browser-use\test_agent
.venv\Scripts\activate

# 单次运行
python test_runner.py

# 指定模型
python test_runner.py --model claude-sonnet-4-5

# 只运行某个 test case（名称子串匹配，大小写不敏感）
python test_runner.py --test-case "signed in"

# 批量重复运行
python test_runner_batch.py --repeat 3
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
from test_agent.llm.llm_config import get_claude_sonnet

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
import test_agent.llm.strip_patch   # 副作用：全局 patch
import test_agent.llm.litellm_patch # 副作用：usage token fallback
```

### 3. shared_steps：跨 test case 复用步骤

同一 `.test.json` 文件内，将多个 test case 共用的步骤提取到顶层 `shared_steps` 字典，在 `steps` 数组中用 `{ "ref": "step_id" }` 引用。`load_test_file()` 加载时自动展开，runner 看到的始终是完整步骤。

```json
{
  "shared_steps": {
    "handle_cart": { "step_name": "...", "step_description": "...", "expected_result": "..." }
  },
  "test_cases": [
    {
      "steps": [
        { "ref": "handle_cart" },
        { "step_name": "site-specific step", "step_description": "...", "expected_result": "..." }
      ]
    }
  ]
}
```

### 5. 配置 Edge 启动页（可选）

`precheckout_skip` 模式依赖 replay.json 第一步自动 goto checkout URL，不需要 Edge 恢复上次页面。Edge 的"从上次停止的地方继续"设置对此模式无影响，无需特别配置。

---

自动从 `happyautoec@outlook.com` 收件箱读取 Nike 验证码邮件，提取数字验证码（4-8位）。
基于 **Outlook 桌面版 COM/MAPI**，无需 OAuth，无需 token，Outlook 运行即可用。

### 4. 反爬虫最佳实践

⭐ **推荐**：使用干净的 User Data Directory（`config.py` 中配置）

```python
EDGE_STABLE_USER_DATA_DIR = 'C:\\tmp2'  # 无历史指纹的干净目录
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
| 自动填充弹窗不出现 | 用 `scripts/debug/test_cdp_click_with_tscon.py` 调试；RDP 场景需先执行 tscon |
| Nike 邮件验证码获取失败 | 确认经典版 Outlook 正在运行且 `happyautoec@outlook.com` 已登录；运行 `python scripts\email_helper.py` 验证 COM 连接 |
| ImportError / venv 问题 | 确认用 `.venv\Scripts\python.exe` 而非系统 Python |

## 📚 文档索引

- `docs/ARCHITECTURE.md` — 整体架构
- `docs/WHY_GPT4O_FAILS.md` — 为什么切换到 Claude
- `docs/USER_DATA_DIR_SOLUTION.md` — 反爬虫最佳实践
- `docs/RDP_Session_Management.md` — RDP 会话管理
- `docs/PROXY_POOL_USAGE.md` — 代理池使用
- `docs/ENHANCED_CLICK.md` — 增强点击方案
- `docs/NIKE_AUTOFILL_SOLUTION.md` — Nike 自动填充方案

---

**维护日期**：2026-04-03
