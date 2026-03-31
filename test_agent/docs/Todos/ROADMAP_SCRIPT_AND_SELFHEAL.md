# Roadmap：脚本化回放 + 自愈式 CI/CD

## 背景

当前架构每个 checkout 测试需要 20+ 个 LLM step，每步 5-8s，总耗时 100-160s。
目标是建立一个全自动精炼闭环：首次由 LLM 探索执行，自动精炼出最短有效路径写入
`replay.json`，后续直接回放（无 LLM，~40s）；回放失败时 LLM 断点续跑，
自动精炼新段并合并，全程无人工介入。

---

## 架构决策记录

### 为什么不用 LLM 生成 Playwright 脚本（Idea 1，已废弃）

最初考虑让 LLM 把探索过程转写为 Playwright 脚本。**根本性缺陷**：

- **selector 静态化**：Playwright 脚本依赖 CSS selector / XPath 字符串，Nike 每次发版
  class/id 都会变，脚本立刻失效，且无自愈能力
- **生成质量不稳定**：LLM 生成的代码边界情况处理差，调试困难，出错只有 exception 没有上下文
- **额外维护成本**：需要独立的 Playwright 环境和脚本版本管理
- **无法利用 browser-use 的 6 级 fallback**：`Agent.rerun_history()` 内置
  `backend_node_id → element_hash → stable_hash → xpath → ax_name → attributes`
  逐级降级匹配，单个属性变了照样能找到元素——这是 Playwright 脚本完全没有的能力

**结论**：`replay.json` + `rerun_history()` 在稳定性、自愈能力、维护成本上全面优于 LLM 生成脚本。

### 为什么不用验证剪枝（逐步删除+验证）

验证剪枝理论上能找到最优最短路径，但在本场景有致命约束：

- Nike 真实网站有 Akamai 反爬，短时间内重复访问 checkout 15 次会触发封禁
- autofill 触发状态不可回滚，每次验证需完整从头跑一遍（100-160s × N 次）
- 代价比全量重跑高一个量级，且稳定性更差

### 选定方案：LLM 语义精炼 + 单次回放验证

```
LLM 探索完（20步 history）
    ↓
LLM 语义分析（1次调用）→ 输出可删除的 step index 列表
    ↓
删除后跑 1 次 rerun() 验证
    ↓
通过 → 写入 replay.json（精炼版）
失败 → 写入 replay.json（规则清洗版，功能正确优先）
```

代价：1次 LLM 调用 + 1次完整回放，相比验证剪枝节省 90% 时间。

### 为什么 replay_steps 存 history.json 而不是 test.json

`AgentHistoryList` 是 browser-use 原生格式，含完整的 `DOMInteractedElement`
（`x_path`、`stable_hash`、`ax_name`、`attributes`），直接驱动 `Agent.rerun_history()`
的 6 级元素 fallback 匹配。test.json 里的 `replay_steps`（`TestCaseReplayStep`
模型）是旧设计，字段不完整，不具备驱动 rerun 的能力。

**实际数据流：**
- 精炼后的黄金路径存为 `test_case/{test_case_name}.replay.json`（`AgentHistoryList` 格式）
- `test.json` 的 `replay_steps` 字段保持为空，不使用

---

## Phase 1：全自动精炼 + 断点续跑（已实现 ✅）

### 执行流程

```
test_runner.py 启动
    ↓
检查 logs/{name}.replay.json 是否存在？
    │
    ├── 不存在 → LLM 完整探索 → HistoryRefiner 精炼 → 存 replay.json
    │
    └── 存在 → ReplayManager.rerun_history()
                    ↓
                成功 → 完成（~40s）
                失败（step K）→ 浏览器保持打开
                    ↓
                LLM 从当前页面状态续跑剩余任务
                    ↓
                新 tail history → HistoryRefiner 精炼 tail
                    ↓
                合并：replay[:K] + refined_tail
                    ↓
                单次 rerun() 验证合并结果
                    ↓
                通过 → 写回 replay.json
                失败 → 写入未精炼合并版（兜底）
```

### 核心组件

#### HistoryRefiner（`test_agent/replay/history_refiner.py`）

**职责**：把含弯路的 `AgentHistoryList` 精炼为最短有效路径。

**步骤 1：规则清洗（零成本，无需 LLM）**

删除明确无用的步骤：
- `action == [None]`（纯思考步骤）
- `result.error` 非空（原本就失败的步骤）
- 连续相同 `stable_hash` + 相同 `action_type`（重复点击同一元素）
- `action_type` 为 `extract`/`screenshot` 且 `interacted_element` 为 None（无副作用观察步骤）

**步骤 2：LLM 语义精炼（1次调用）**

将清洗后的 history 序列化为结构化摘要喂给 LLM，输出可删除的 step index。

硬性约束（LLM 不得违反）：
- `url_before != url_after` → 绝对不能删
- `result_error != null` → 绝对不能删
- `action_type` 为 `uia_*` / `logmonitor_*` / `clear_site_data` 等自定义关键 actions → 绝对不能删
- 第一步和最后一步 → 绝对不能删

**步骤 3：单次 rerun() 验证**

用精炼后的步骤跑 1 次完整回放：
- 通过 → 返回精炼版
- 失败 → 返回规则清洗版（兜底）

---

#### ReplayManager（`test_agent/replay/replay_manager.py`）

**职责**：管理 replay.json 的读写，封装 rerun_history() 的失败处理与断点续跑逻辑。

**关键设计：rerun() 失败时不关闭浏览器**

`ReplayManager` 创建共享 `BrowserSession`，传给 rerun Agent 和 heal Agent，
失败后 `BrowserSession` 保持打开，LLM 接管时看到的是失败那一刻的真实页面状态。

**rerun() 失败判断**

捕获 `RuntimeError("Step N failed after X attempts: ...")` 后用正则解析
`failed_step_index`，精确定位断点。

**回放速度优化**

所有回放参数集中在 `config.py`：
- `RERUN_MAX_RETRIES = 2`
- `RERUN_DELAY_BETWEEN_ACTIONS = 1.0`（每步固定等待）
- `RERUN_MAX_STEP_INTERVAL = 3.0`（压缩 LLM 探索时的 saved interval，默认上限 45s）

实测：11步 Signed In 流程从 LLM 探索的 ~160s 压缩到回放 ~40s。

---

### 文件结构

```
test_agent/
├── replay/
│   ├── history_refiner.py    # HistoryRefiner
│   └── replay_manager.py     # ReplayManager
├── test_case/
│   ├── nike.test.json                            # 测试用例定义
│   ├── nike_autofill_guest.replay.json           # 精炼后黄金路径（12步）
│   └── nike_autofill_signed_in.replay.json       # 精炼后黄金路径（11步）
├── logs/                                         # 运行日志（预留）
├── config.py                                     # 所有配置集中管理（含 replay 参数）
└── test_runner.py                                # 集成 ReplayManager，输出耗时日志
```

---

## Phase 2：自愈 CI/CD

已拆分为独立文档：[ROADMAP_SELFHEAL_CICD.md](./ROADMAP_SELFHEAL_CICD.md)

---

## 现有工程基础

| 组件 | 文件 | 用途 |
|------|------|------|
| LLM 执行引擎 | `test_runner.py` | 探索模式 + 续跑模式 |
| Agent.rerun_history() | `browser_use/agent/service.py` | 回放驱动，6级元素 fallback |
| AgentHistoryList | `browser_use/agent/views.py` | replay.json 格式，save/load |
| DOMInteractedElement | `browser_use/dom/views.py` | 含 x_path、stable_hash、ax_name |
| 自定义 actions | `register_custom_actions.py` | rerun 时需同样注册 |
| 回放配置 | `config.py` | RERUN_* 常量统一管理 |

---

**维护日期**：2026-03-31
