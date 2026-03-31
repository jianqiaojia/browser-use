# Roadmap：脚本化回放 + 自愈式 CI/CD

## 背景

当前架构每个 checkout 测试需要 20+ 个 LLM step，每步 5-8s，总耗时 100-160s。
目标是建立一个全自动精炼闭环：首次由 LLM 探索执行，自动精炼出最短有效路径写入
`replay_steps`，后续直接回放（无 LLM，5-10s）；回放失败时 LLM 断点续跑，
自动精炼新段并合并，全程无人工介入。

---

## 架构决策记录

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
通过 → 写入 replay_steps（精炼版）
失败 → 写入 replay_steps（未精炼原始版，功能正确优先）
```

代价：1次 LLM 调用 + 1次完整回放，相比验证剪枝节省 90% 时间。

### 为什么 replay_steps 存 history.json 而不是 test.json

`AgentHistoryList` 是 browser-use 原生格式，含完整的 `DOMInteractedElement`
（`x_path`、`stable_hash`、`ax_name`、`attributes`），直接驱动 `Agent.rerun()`
的 6 级元素 fallback 匹配。test.json 里的 `replay_steps`（`TestCaseReplayStep`
模型）是旧设计，字段不完整，不具备驱动 rerun() 的能力。

**实际数据流：**
- 精炼后的黄金路径存为 `logs/{test_case_name}.replay.json`（`AgentHistoryList` 格式）
- `test.json` 的 `replay_steps` 字段保持为空，不使用

---

## Phase 1：全自动精炼 + 断点续跑

### 执行流程

```
test_runner.py 启动
    ↓
检查 logs/{name}.replay.json 是否存在？
    │
    ├── 不存在 → LLM 完整探索 → HistoryRefiner 精炼 → 存 replay.json
    │
    └── 存在 → ReplayManager.rerun()
                    ↓
                成功 → 完成（5-10s）
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

**输入**：原始 `AgentHistoryList`（20+ 步）

**步骤 1：规则清洗（零成本，无需 LLM）**

删除明确无用的步骤：
- `action == [None]`（纯思考步骤）
- `result.error` 非空（原本就失败的步骤）
- 连续相同 `stable_hash` + 相同 `action_type`（重复点击同一元素）
- `action_type` 为 `extract`/`screenshot` 且 `interacted_element` 为 None（无副作用观察步骤）

**步骤 2：LLM 语义精炼（1次调用）**

将清洗后的 history 序列化为结构化摘要，每步包含：
```python
{
    "step": 3,
    "goal": "click Proceed to Checkout",
    "action_type": "click",
    "element_tag": "BUTTON",
    "element_ax_name": "Proceed to Checkout",
    "url_before": "nike.com/cart",
    "url_after": "nike.com/checkout",
    "result_success": True,
}
```

Prompt 约束（硬编码规则，LLM 不得违反）：
- `url_before != url_after` → 绝对不能删
- `result_error != null` → 绝对不能删
- `action_type` 为 `uia_*` / `logmonitor_*` / `clear_site_data` → 绝对不能删（自定义关键 actions）

LLM 输出：可删除的 step index 列表（JSON 数组）+ 每个的删除理由。

**步骤 3：单次 rerun() 验证**

用精炼后的步骤跑 1 次完整回放：
- 通过 → 返回精炼版
- 失败 → 返回原始清洗版（规则清洗后，未 LLM 精炼）

**输出**：精炼后的 `AgentHistoryList`

---

#### ReplayManager（`test_agent/replay/replay_manager.py`）

**职责**：管理 replay.json 的读写，封装 rerun() 的失败处理与断点续跑逻辑。

**关键设计：rerun() 失败时不关闭浏览器**

`Agent.rerun()` 在 `finally` 块里调 `await self.close()`，需要在外部通过
`Agent` 的 `browser_session` 参数传入一个已存在的 session，或者 fork 出一个
不 close browser 的 rerun 变体。

实现方式：`ReplayManager` 创建 `BrowserSession`，传给 `Agent`，失败后
`BrowserSession` 保持打开，直接传给续跑的新 `Agent`。

**rerun() 失败判断**

通过 `ActionResult.error` 检测失败步骤的 index（rerun 内部已记录），
捕获 `RuntimeError` 后解析 "Step N failed" 提取 `failed_step_index`。

---

### 文件结构

```
test_agent/
├── replay/
│   ├── __init__.py
│   ├── history_refiner.py    # HistoryRefiner
│   └── replay_manager.py     # ReplayManager
├── logs/
│   ├── nike_autofill_guest.history.json     # LLM 探索原始历史（已有）
│   └── nike_autofill_guest.replay.json      # 精炼后黄金路径（待生成）
└── test_runner.py                           # 集成 ReplayManager
```

---

### 实施计划

#### Phase 1a（~2天）：HistoryRefiner

- [ ] 实现规则清洗（step 1）
- [ ] 实现 history 摘要序列化
- [ ] 实现 LLM 精炼 prompt + 输出解析
- [ ] 实现单次 rerun() 验证 + 兜底逻辑
- [ ] 单元测试：用 `logs/*.history.json` 验证精炼结果合理

#### Phase 1b（~2天）：ReplayManager + test_runner 集成

- [ ] 实现 BrowserSession 共享（跨 Agent 实例复用，不 close）
- [ ] 实现 rerun() 失败捕获 + failed_step_index 提取
- [ ] 实现 LLM 续跑（从当前浏览器状态接管）
- [ ] 实现 tail 精炼 + 合并 + 验证
- [ ] 修改 `test_runner.py`：replay.json 存在时走 ReplayManager，不存在时走 LLM + Refiner
- [ ] 端到端验证：Nike Guest 流程精炼后稳定回放 3 次

---

## Phase 2：自愈 CI/CD（依赖 Phase 1）

暂缓，等 Phase 1 稳定后再规划。核心思路不变：
- 测试失败 → LLM 分析根因 → 修改白名单目录代码 → 回归验证 → 提 PR

---

## 现有工程基础

| 组件 | 文件 | 用途 |
|------|------|------|
| LLM 执行引擎 | `test_runner.py` | 探索模式 + 续跑模式 |
| Agent.rerun() | `browser_use/agent/service.py:3056` | 回放驱动，6级元素 fallback |
| AgentHistoryList | `browser_use/agent/views.py:610` | replay.json 格式，save/load |
| DOMInteractedElement | `browser_use/dom/views.py:975` | 含 x_path、stable_hash、ax_name |
| 自定义 actions | `register_custom_actions.py` | rerun 时需同样注册 |
| 原始历史文件 | `logs/*.history.json` | HistoryRefiner 开发期间的测试输入 |

---

**维护日期**：2026-03-30
